"""Export HTML visualization of the knowledge graph."""
import json
from collections import defaultdict
from pathlib import Path


HTML_MAX_NODES = 10_000
HTML_MAX_EDGES = 50_000


def _aggregate_communities(graph, metadata):
    import networkx as nx

    aggregated = nx.Graph()
    labels = metadata.get('labels', {})
    counts = defaultdict(int)
    for _, data in graph.nodes(data=True):
        community = data.get('community', -1)
        counts[community] += 1
    for community, count in counts.items():
        aggregated.add_node(
            str(community),
            label=labels.get(str(community), f'Community {community}'),
            community=community,
            member_count=count,
        )
    edge_counts = defaultdict(int)
    for source, target in graph.edges():
        left = graph.nodes[source].get('community', -1)
        right = graph.nodes[target].get('community', -1)
        if left == right:
            continue
        edge_counts[tuple(sorted((str(left), str(right))))] += 1
    for (left, right), count in edge_counts.items():
        aggregated.add_edge(left, right, relation=f'{count} cross-community edges')
    aggregated.graph['aggregated'] = True
    return aggregated


def export_html(directory: str, quiet: bool = False, full_html: bool = False):
    """Generate interactive HTML graph visualization."""
    try:
        from pyvis.network import Network
        import networkx as nx
        from networkx.readwrite import json_graph
    except ImportError:
        raise ImportError('pyvis and networkx required. pip install pyvis networkx')

    root = Path(directory).resolve()
    graph_path = root / 'astify-out' / 'graph.json'
    summary_path = root / 'astify-out' / 'graph-summary.json'
    database_path = root / 'astify-out' / 'astify.db'
    analysis_path = root / 'astify-out' / 'analysis.json'

    if not graph_path.exists() and not summary_path.exists() and not database_path.exists():
        print('ERROR: No graph found. Run extract + build first.')
        return

    if full_html and database_path.exists():
        from astify.storage import load_graph

        G = load_graph(database_path)
    else:
        selected = summary_path if summary_path.exists() else graph_path
        data = json.loads(selected.read_text(encoding='utf-8'))
        G = json_graph.node_link_graph(data, edges='links')

    meta = {}
    if analysis_path.exists():
        meta = json.loads(analysis_path.read_text(encoding='utf-8'))
    if not full_html and (
        G.number_of_nodes() > HTML_MAX_NODES
        or G.number_of_edges() > HTML_MAX_EDGES
    ):
        if not quiet:
            print(
                f'Aggregating HTML: {G.number_of_nodes():,} nodes, '
                f'{G.number_of_edges():,} edges exceed safe browser limit',
                flush=True,
            )
        G = _aggregate_communities(G, meta)

    # Map community → color
    community_colors = {}
    palette = [
        '#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f',
        '#edc948', '#b07aa1', '#ff9da7', '#9c755f', '#bab0ac',
    ]
    for nid, ndata in G.nodes(data=True):
        cid = ndata.get('community', -1)
        if cid not in community_colors:
            community_colors[cid] = palette[len(community_colors) % len(palette)]

    net = Network(height='800px', width='100%', bgcolor='#1a1a2e',
                  font_color='#ffffff', directed=False)
    stabilization = 200 if G.number_of_nodes() <= 2_000 else 50
    net.set_options(f"""
    {{
      "nodes": {{ "scaling": {{ "min": 10, "max": 40 }}, "font": {{ "size": 12, "color": "#ffffff" }} }},
      "physics": {{ "barnesHut": {{ "gravitationalConstant": -2000, "springLength": 150 }},
                   "stabilization": {{ "iterations": {stabilization} }} }}
    }}
    """)

    for nid, ndata in G.nodes(data=True):
        label = ndata.get('label', nid)[:40]
        cid = ndata.get('community', -1)
        color = community_colors.get(cid, '#999999')
        size = max(10, min(40, G.degree(nid) * 3))
        member_count = ndata.get('member_count')
        title = f'{label} ({member_count} nodes)' if member_count else label
        net.add_node(nid, label=label, title=title, color=color,
                     size=size)

    for u, v, edata in G.edges(data=True):
        rel = edata.get('relation', '')
        net.add_edge(u, v, title=rel)

    html_path = root / 'astify-out' / 'graph.html'
    net.save_graph(str(html_path))

    if not quiet:
        print(f'Saved: {html_path}')
