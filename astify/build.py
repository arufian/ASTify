"""Graph building with bounded analysis and scalable persistence."""
import json
import time
from collections import Counter
from pathlib import Path


EXACT_MAX_NODES = 2_000
EXACT_MAX_EDGES = 20_000
SAMPLED_MAX_EDGES = 500_000
SAMPLED_SOURCES = 64
FULL_JSON_MAX_NODES = 50_000
FULL_JSON_MAX_EDGES = 250_000
ANALYSIS_SYMBOL_KINDS = {
    'class', 'interface', 'enum', 'trigger', 'method', 'constructor', 'function',
}


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _serialize_graph(graph) -> dict:
    return {
        'directed': False,
        'multigraph': False,
        'graph': dict(graph.graph),
        'nodes': [
            {'id': node_id, **data}
            for node_id, data in graph.nodes(data=True)
        ],
        'links': [
            {'source': source, 'target': target, **data}
            for source, target, data in graph.edges(data=True)
        ],
    }


def _analysis_projection(graph):
    """Create compact graph for clustering/reporting while retaining query graph."""
    import networkx as nx

    projected = nx.Graph()
    projected.graph.update(graph.graph)
    for node_id, data in graph.nodes(data=True):
        if (
            data.get('file_type') != 'symbol'
            or data.get('symbol_kind') in ANALYSIS_SYMBOL_KINDS
        ):
            projected.add_node(node_id, **data)

    for source, target, data in graph.edges(data=True):
        if source in projected and target in projected:
            projected.add_edge(source, target, **data)

    # Collapse owner → call occurrence → resolved definition into one analysis
    # edge. Detailed occurrence nodes remain in the persisted query graph.
    for call_id, call_data in graph.nodes(data=True):
        if call_data.get('symbol_kind') != 'call':
            continue
        owners = []
        targets = []
        for neighbor in graph.neighbors(call_id):
            edge = graph[call_id][neighbor]
            edge_source = edge.get('edge_source')
            edge_target = edge.get('edge_target')
            relation = edge.get('relation')
            if relation == 'calls' and edge_target == call_id:
                owners.append(edge_source)
            elif relation == 'resolves_to' and edge_source == call_id:
                targets.append(edge_target)
        for owner in owners:
            for target in targets:
                if owner in projected and target in projected and owner != target:
                    projected.add_edge(
                        owner,
                        target,
                        relation='calls',
                        confidence='EXTRACTED',
                        confidence_score=1.0,
                        source_file=call_data.get('source_file', ''),
                        source_location=call_data.get('source_location'),
                        edge_source=owner,
                        edge_target=target,
                        projected=True,
                    )
    return projected


def _bridge_surprises(graph, nodes_data: dict, limit: int = 10) -> list[dict]:
    """Rank cross-community edges without global shortest-path computation."""
    candidates = []
    for source, target in graph.edges():
        source_community = nodes_data[source].get('community', -1)
        target_community = nodes_data[target].get('community', -1)
        if source_community < 0 or source_community == target_community:
            continue
        score = 1.0 / max(1, min(graph.degree(source), graph.degree(target)))
        candidates.append((score, source, target))
    candidates.sort(reverse=True)
    return [
        {
            'source': nodes_data[source]['label'],
            'target': nodes_data[target]['label'],
            'betweenness': round(score, 4),
            'metric': 'cross_community_bridge',
            'source_id': source,
            'target_id': target,
        }
        for score, source, target in candidates[:limit]
    ]


def _analyze_graph(graph, nodes_data: dict, full_analysis: bool = False,
                   progress: bool = False) -> tuple[dict, dict]:
    """Cluster graph and compute size-appropriate bridge metrics."""
    import networkx as nx

    communities = {}
    _log(
        progress,
        f'Clustering analysis graph: {graph.number_of_nodes():,} nodes, '
        f'{graph.number_of_edges():,} edges',
    )
    if graph.number_of_edges() > 0 and graph.number_of_nodes() >= 3:
        from networkx.algorithms.community import louvain_communities

        raw = louvain_communities(graph, seed=42)
        for community_id, node_set in enumerate(raw):
            communities[community_id] = list(node_set)
            for node_id in node_set:
                nodes_data[node_id]['community'] = community_id
                graph.nodes[node_id]['community'] = community_id

    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    if edge_count == 0 or node_count < 5:
        analysis_mode = 'none'
        surprises = []
    elif full_analysis or (
        node_count <= EXACT_MAX_NODES and edge_count <= EXACT_MAX_EDGES
    ):
        analysis_mode = 'exact'
        _log(progress, 'Computing exact edge betweenness...')
        centrality = nx.edge_betweenness_centrality(graph)
        top_edges = sorted(
            centrality.items(), key=lambda item: item[1], reverse=True
        )[:10]
        surprises = [
            {
                'source': nodes_data[source]['label'],
                'target': nodes_data[target]['label'],
                'betweenness': round(score, 4),
                'metric': 'exact_betweenness',
                'source_id': source,
                'target_id': target,
            }
            for (source, target), score in top_edges if score > 0
        ]
    elif edge_count <= SAMPLED_MAX_EDGES:
        analysis_mode = 'sampled'
        sample_size = min(SAMPLED_SOURCES, node_count)
        _log(
            progress,
            f'Computing sampled edge betweenness ({sample_size} sources)...',
        )
        centrality = nx.edge_betweenness_centrality(
            graph, k=sample_size, seed=42
        )
        top_edges = sorted(
            centrality.items(), key=lambda item: item[1], reverse=True
        )[:10]
        surprises = [
            {
                'source': nodes_data[source]['label'],
                'target': nodes_data[target]['label'],
                'betweenness': round(score, 4),
                'metric': 'sampled_betweenness',
                'source_id': source,
                'target_id': target,
            }
            for (source, target), score in top_edges if score > 0
        ]
    else:
        analysis_mode = 'community_bridges'
        _log(
            progress,
            'Graph exceeds betweenness limit; ranking community bridges...',
        )
        surprises = _bridge_surprises(graph, nodes_data)

    return communities, {
        'analysis_mode': analysis_mode,
        'surprises': surprises,
    }


def _build_networks(semantic: dict, full_analysis: bool = False,
                    progress: bool = False):
    import networkx as nx

    started = time.perf_counter()
    graph = nx.Graph()
    graph.graph.update({
        'schema_version': semantic.get('schema_version', 1),
        'structural_parser': semantic.get('structural_parser'),
    })
    nodes_data = {}
    for node in semantic.get('nodes', []):
        node_id = node['id']
        attributes = {
            'label': node.get('label', node_id),
            'file_type': node.get('file_type', 'concept'),
            'source_file': node.get('source_file', ''),
            'source_location': node.get('source_location'),
            'symbol_kind': node.get('symbol_kind'),
            'parser': node.get('parser'),
            'language': node.get('language'),
            'community': -1,
        }
        graph.add_node(node_id, **attributes)
        nodes_data[node_id] = {'id': node_id, **attributes}

    for edge in semantic.get('edges', []):
        source = edge['source']
        target = edge['target']
        if source not in graph or target not in graph:
            continue
        graph.add_edge(
            source,
            target,
            relation=edge.get('relation', 'relates_to'),
            confidence=edge.get('confidence', 'INFERRED'),
            confidence_score=edge.get('confidence_score', 0.75),
            source_file=edge.get('source_file', ''),
            source_location=edge.get('source_location'),
            edge_source=source,
            edge_target=target,
        )

    _log(
        progress,
        f'Loaded detailed graph: {graph.number_of_nodes():,} nodes, '
        f'{graph.number_of_edges():,} edges',
    )
    projected = _analysis_projection(graph)
    communities, analysis = _analyze_graph(
        projected, nodes_data, full_analysis=full_analysis, progress=progress
    )

    # Excluded occurrence nodes inherit an adjacent owner's community when
    # possible, keeping detailed query output consistent with the projection.
    for node_id, data in nodes_data.items():
        if data['community'] >= 0:
            graph.nodes[node_id]['community'] = data['community']
    for node_id in graph:
        if nodes_data[node_id]['community'] >= 0:
            continue
        neighbor_communities = [
            nodes_data[neighbor]['community']
            for neighbor in graph.neighbors(node_id)
            if nodes_data[neighbor]['community'] >= 0
        ]
        if neighbor_communities:
            community = Counter(neighbor_communities).most_common(1)[0][0]
            nodes_data[node_id]['community'] = community
            graph.nodes[node_id]['community'] = community

    degrees = sorted(projected.degree(), key=lambda item: item[1], reverse=True)
    gods = [
        {
            'id': node_id,
            'label': nodes_data[node_id]['label'],
            'degree': degree,
            'community': nodes_data[node_id]['community'],
        }
        for node_id, degree in degrees[:10] if degree > 0
    ]

    cohesion = {}
    for community_id, members in communities.items():
        subgraph = projected.subgraph(members)
        cohesion[community_id] = round(nx.density(subgraph), 4)

    labels = {}
    for community_id, members in communities.items():
        terms = []
        for node_id in members[:15]:
            terms.extend(
                word for word in nodes_data[node_id]['label'].lower().split()
                if len(word) >= 3
            )
        best = [word for word, _ in Counter(terms).most_common(3)]
        labels[community_id] = (
            ' '.join(best).title() if best else f'Community {community_id}'
        )

    questions = []
    if gods:
        questions.append(
            f"How does {gods[0]['label']} connect to other components?"
        )
    if len(communities) >= 2:
        first, second = list(communities)[:2]
        questions.append(
            f"What bridges {labels[first]} and {labels[second]}?"
        )
    questions.append('Which concepts are most central to the architecture?')

    metadata = {
        'communities': {
            str(community_id): members
            for community_id, members in communities.items()
        },
        'cohesion': {
            str(community_id): score
            for community_id, score in cohesion.items()
        },
        'gods': gods,
        'surprises': analysis['surprises'],
        'questions': questions,
        'labels': {
            str(community_id): label
            for community_id, label in labels.items()
        },
        'num_nodes': graph.number_of_nodes(),
        'num_edges': graph.number_of_edges(),
        'analysis_nodes': projected.number_of_nodes(),
        'analysis_edges': projected.number_of_edges(),
        'num_communities': len(communities),
        'analysis_mode': analysis['analysis_mode'],
        'input_tokens': semantic.get('input_tokens', 0),
        'output_tokens': semantic.get('output_tokens', 0),
        'schema_version': semantic.get('schema_version', 1),
        'structural_parser': semantic.get('structural_parser'),
        'build_seconds': round(time.perf_counter() - started, 3),
    }
    return graph, projected, metadata


def build_from_semantic(
    semantic: dict,
    root: str = '.',
    full_analysis: bool = False,
) -> tuple[dict, dict]:
    """Build a detailed graph and bounded analysis metadata."""
    graph, _, metadata = _build_networks(
        semantic, full_analysis=full_analysis, progress=False
    )
    return _serialize_graph(graph), metadata


def build_graph(
    directory: str,
    semantic: dict,
    quiet: bool = False,
    full_analysis: bool = False,
    full_json: bool = False,
) -> dict:
    """Build, analyze, persist, and optionally export full graph JSON."""
    from astify.storage import save_graph

    root = Path(directory).resolve()
    out_dir = root / 'astify-out'
    out_dir.mkdir(parents=True, exist_ok=True)
    _log(not quiet, 'Building graph...')
    graph, projected, metadata = _build_networks(
        semantic,
        full_analysis=full_analysis,
        progress=not quiet,
    )

    database_path = out_dir / 'astify.db'
    _log(not quiet, 'Writing SQLite graph store...')
    save_graph(database_path, graph, metadata)

    summary_path = out_dir / 'graph-summary.json'
    summary_path.write_text(
        json.dumps(_serialize_graph(projected), indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    write_full_json = full_json or (
        graph.number_of_nodes() <= FULL_JSON_MAX_NODES
        and graph.number_of_edges() <= FULL_JSON_MAX_EDGES
    )
    graph_path = out_dir / 'graph.json'
    if write_full_json:
        _log(not quiet, 'Writing full graph.json...')
        graph_path.write_text(
            json.dumps(_serialize_graph(graph), indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
    else:
        graph_path.unlink(missing_ok=True)
        _log(
            not quiet,
            'Full graph.json skipped: graph exceeds safe export limit. '
            'Use --full-json to force it.',
        )

    analysis_path = out_dir / 'analysis.json'
    analysis_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    _log(
        not quiet,
        f'Graph: {metadata["num_nodes"]:,} nodes, '
        f'{metadata["num_edges"]:,} edges; '
        f'analysis={metadata["analysis_mode"]} on '
        f'{metadata["analysis_nodes"]:,} projected nodes',
    )
    _log(not quiet, f'Saved: {database_path}')
    _log(not quiet, f'Saved: {summary_path}')
    _log(not quiet, f'Saved: {analysis_path}')
    return {
        'graph': _serialize_graph(graph) if write_full_json else None,
        'summary': _serialize_graph(projected),
        'meta': metadata,
    }
