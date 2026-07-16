"""Graph building: merge extraction, build NetworkX graph, cluster, analyze."""
import json
from pathlib import Path
from collections import defaultdict


def build_from_semantic(semantic: dict, root: str = '.') -> tuple[dict, dict]:
    """Build NetworkX graph from semantic extraction dict.

    Returns a node-link graph dict compatible with graph.json.
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError('networkx required for build. pip install networkx')

    G = nx.Graph()
    nodes_data = {}
    edges_data = []

    for node in semantic.get('nodes', []):
        nid = node['id']
        G.add_node(nid)
        nodes_data[nid] = {
            'id': nid,
            'label': node.get('label', nid),
            'file_type': node.get('file_type', 'concept'),
            'source_file': node.get('source_file', ''),
            'source_location': node.get('source_location'),
            'symbol_kind': node.get('symbol_kind'),
            'community': -1,
        }

    for edge in semantic.get('edges', []):
        src = edge['source']
        tgt = edge['target']
        if src not in G.nodes or tgt not in G.nodes:
            continue
        rel = edge.get('relation', 'relates_to')
        conf = edge.get('confidence', 'INFERRED')
        score = edge.get('confidence_score', 0.75)
        G.add_edge(src, tgt, relation=rel, confidence=conf,
                   confidence_score=score,
                   source_file=edge.get('source_file', ''),
                   source_location=edge.get('source_location'))

    # Community detection (Louvain)
    communities = {}
    if G.number_of_edges() > 0 and G.number_of_nodes() >= 3:
        try:
            from networkx.algorithms.community import louvain_communities
            raw = louvain_communities(G, seed=42)
            for cid, node_set in enumerate(raw):
                communities[cid] = list(node_set)
                for nid in node_set:
                    nodes_data[nid]['community'] = cid
        except ImportError:
            try:
                from community import best_partition
                partition = best_partition(G)
                for nid, cid in partition.items():
                    nodes_data[nid]['community'] = cid
                    communities.setdefault(cid, []).append(nid)
            except ImportError:
                pass

    # God nodes: highest degree nodes
    degrees = sorted(G.degree(), key=lambda x: x[1], reverse=True)
    gods = [{'id': nid, 'label': nodes_data[nid]['label'],
             'degree': deg, 'community': nodes_data[nid]['community']}
            for nid, deg in degrees[:10] if deg > 0]

    # Surprising connections: high-betweenness edges
    surprises = []
    if G.number_of_edges() > 0 and G.number_of_nodes() >= 5:
        try:
            bc = nx.edge_betweenness_centrality(G)
            top_edges = sorted(bc.items(), key=lambda x: x[1], reverse=True)[:10]
            for (u, v), cent in top_edges:
                if cent > 0:
                    surprises.append({
                        'source': nodes_data[u]['label'],
                        'target': nodes_data[v]['label'],
                        'betweenness': round(cent, 4),
                        'source_id': u, 'target_id': v,
                    })
        except Exception:
            pass

    # Cohesion scores
    cohesion = {}
    for cid, members in communities.items():
        if len(members) < 2:
            cohesion[cid] = 0.0
            continue
        subg = G.subgraph(members)
        if subg.number_of_nodes() > 1 and subg.number_of_edges() > 0:
            density = nx.density(subg)
        else:
            density = 0.0
        cohesion[cid] = round(density, 4)

    # Generate plain-language community labels
    labels = {}
    for cid, members in communities.items():
        top_terms = []
        for nid in members[:15]:
            label = nodes_data[nid]['label']
            for word in label.lower().split():
                if len(word) >= 3:
                    top_terms.append(word)
        from collections import Counter
        tc = Counter(top_terms)
        best = [w for w, _ in tc.most_common(3)]
        labels[cid] = ' '.join(best).title() if best else f'Community {cid}'

    # Suggest questions
    questions = []
    if gods:
        top_god = gods[0]
        questions.append(f"How does {top_god['label']} connect to other components?")
    if len(communities) >= 2:
        cids = list(communities.keys())[:2]
        q1 = labels.get(cids[0], f'Community {cids[0]}')
        q2 = labels.get(cids[1], f'Community {cids[1]}')
        questions.append(f"What bridges {q1} and {q2}?")
    questions.append("Which concepts are most central to the architecture?")

    # Build node-link data (Graphify compatible)
    node_link_data = {
        'directed': False,
        'multigraph': False,
        'graph': {},
        'nodes': [{'id': nid, **nodes_data[nid]} for nid in G.nodes()],
        'links': [
            {
                'source': u,
                'target': v,
                'relation': G[u][v].get('relation', 'relates_to'),
                'confidence': G[u][v].get('confidence', 'INFERRED'),
                'confidence_score': G[u][v].get('confidence_score', 0.75),
                'source_file': G[u][v].get('source_file', ''),
                'source_location': G[u][v].get('source_location'),
            }
            for u, v in G.edges()
        ],
    }

    meta = {
        'communities': {str(k): v for k, v in communities.items()},
        'cohesion': {str(k): v for k, v in cohesion.items()},
        'gods': gods,
        'surprises': surprises,
        'questions': questions,
        'labels': {str(k): v for k, v in labels.items()},
        'num_nodes': G.number_of_nodes(),
        'num_edges': G.number_of_edges(),
        'num_communities': len(communities),
        'input_tokens': semantic.get('input_tokens', 0),
        'output_tokens': semantic.get('output_tokens', 0),
    }

    return node_link_data, meta


def build_graph(directory: str, semantic: dict, quiet: bool = False) -> dict:
    """Run full build pipeline from semantic extraction.

    Saves graph.json and astify-out/analysis.json.
    """
    root = Path(directory).resolve()
    out_dir = root / 'astify-out'
    out_dir.mkdir(parents=True, exist_ok=True)

    if not quiet:
        print('Building graph...')

    node_link, meta = build_from_semantic(semantic, str(root))

    # Save graph.json
    graph_path = out_dir / 'graph.json'
    with open(graph_path, 'w', encoding='utf-8') as f:
        json.dump(node_link, f, indent=2, ensure_ascii=False)

    # Save analysis
    analysis_path = out_dir / 'analysis.json'
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    if not quiet:
        print(f'Graph: {meta["num_nodes"]} nodes, {meta["num_edges"]} edges, '
              f'{meta["num_communities"]} communities')
        print(f'Saved: {graph_path}')
        print(f'Saved: {analysis_path}')

    return {'graph': node_link, 'meta': meta}
