"""Export HTML visualization of the knowledge graph."""
import json
from pathlib import Path


def export_html(directory: str, quiet: bool = False):
    """Generate interactive HTML graph visualization."""
    try:
        from pyvis.network import Network
        import networkx as nx
        from networkx.readwrite import json_graph
    except ImportError:
        raise ImportError('pyvis and networkx required. pip install pyvis networkx')

    root = Path(directory).resolve()
    graph_path = root / 'astify-out' / 'graph.json'
    analysis_path = root / 'astify-out' / 'analysis.json'

    if not graph_path.exists():
        print('ERROR: No graph found. Run extract + build first.')
        return

    data = json.loads(graph_path.read_text(encoding='utf-8'))
    G = json_graph.node_link_graph(data, edges='links')

    meta = {}
    if analysis_path.exists():
        meta = json.loads(analysis_path.read_text(encoding='utf-8'))
    labels = meta.get('labels', {})

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
    net.set_options("""
    {
      "nodes": { "scaling": { "min": 10, "max": 40 }, "font": { "size": 12, "color": "#ffffff" } },
      "physics": { "barnesHut": { "gravitationalConstant": -2000, "springLength": 150 },
                   "stabilization": { "iterations": 200 } }
    }
    """)

    for nid, ndata in G.nodes(data=True):
        label = ndata.get('label', nid)[:40]
        cid = ndata.get('community', -1)
        color = community_colors.get(cid, '#999999')
        size = max(10, min(40, G.degree(nid) * 3))
        net.add_node(nid, label=label, title=label, color=color,
                     size=size)

    for u, v, edata in G.edges(data=True):
        rel = edata.get('relation', '')
        net.add_edge(u, v, title=rel)

    html_path = root / 'astify-out' / 'graph.html'
    net.save_graph(str(html_path))

    if not quiet:
        print(f'Saved: {html_path}')
