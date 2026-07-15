"""Graph query: BFS/DFS traversal, path finding, node explanation."""
import json
import re
from pathlib import Path
from collections import Counter


def _load_graph(directory: str) -> tuple:
    root = Path(directory).resolve()
    graph_path = root / 'astify-out' / 'graph.json'

    if not graph_path.exists():
        print('ERROR: No graph found. Run `astify extract .` then `astify build .` first.')
        raise SystemExit(1)

    try:
        import networkx as nx
        from networkx.readwrite import json_graph
    except ImportError:
        raise ImportError('networkx required. pip install networkx')

    data = json.loads(graph_path.read_text(encoding='utf-8'))
    G = json_graph.node_link_graph(data, edges='links')
    return G, root


def _build_vocab(G) -> list[str]:
    """Extract vocabulary tokens from node labels."""
    vocab = set()
    for nid, ndata in G.nodes(data=True):
        label = ndata.get('label', '') or ''
        for token in re.findall(r'[^\W\d_]+', label, re.UNICODE):
            parts = re.findall(r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+',
                               token) or [token]
            for p in parts:
                t = p.lower()
                if 3 <= len(t) <= 30:
                    vocab.add(t)
    return sorted(vocab)


def _find_start_nodes(G, terms: list[str], top_k: int = 3) -> list:
    scored = []
    for nid, ndata in G.nodes(data=True):
        label = (ndata.get('label', '') or '').lower()
        score = sum(1 for t in terms if t.lower() in label)
        if score > 0:
            scored.append((score, nid))
    scored.sort(reverse=True)
    return [nid for _, nid in scored[:top_k]]


def query_graph(question: str, mode: str = 'bfs', budget: int = 2000,
                directory: str = '.', quiet: bool = False):
    G, root = _load_graph(directory)
    vocab = _build_vocab(G)

    terms = [t for t in question.lower().split() if len(t) >= 3]
    matched = [t for t in terms if t in vocab]
    if not matched:
        print('No vocabulary match. Available terms:', vocab[:20], '...')
        return

    if not quiet:
        print(f'Query expanded: {matched}')

    start_nodes = _find_start_nodes(G, matched)

    if not start_nodes:
        print('No matching nodes found.')
        return

    subgraph_nodes = set()
    subgraph_edges = []

    if mode == 'dfs':
        visited = set()
        stack = [(n, 0) for n in reversed(start_nodes)]
        while stack:
            node, depth = stack.pop()
            if node in visited or depth > 6:
                continue
            visited.add(node)
            subgraph_nodes.add(node)
            for neighbor in G.neighbors(node):
                if neighbor not in visited:
                    stack.append((neighbor, depth + 1))
                    subgraph_edges.append((node, neighbor))
    else:
        frontier = set(start_nodes)
        subgraph_nodes = set(start_nodes)
        for _ in range(3):
            next_frontier = set()
            for n in frontier:
                for neighbor in G.neighbors(n):
                    if neighbor not in subgraph_nodes:
                        next_frontier.add(neighbor)
                        subgraph_edges.append((n, neighbor))
            subgraph_nodes.update(next_frontier)
            frontier = next_frontier

    char_budget = budget * 4
    lines = [f'Traversal: {mode.upper()} | {len(subgraph_nodes)} nodes']
    for nid in list(subgraph_nodes)[:30]:
        d = G.nodes[nid]
        lines.append(f'  {d.get("label", nid)} [{d.get("file_type","")}'
                     f' src={d.get("source_file","")}]')
    for u, v in subgraph_edges[:50]:
        edge = G[u][v]
        lines.append(f'  {G.nodes[u].get("label",u)}'
                     f' --{edge.get("relation","")}'
                     f' [{edge.get("confidence","")}]-->'
                     f' {G.nodes[v].get("label",v)}')

    output = '\n'.join(lines)
    if len(output) > char_budget:
        output = output[:char_budget] + \
                 f'\n... truncated at ~{budget} tokens'
    print(output)


def find_path(node_a: str, node_b: str, directory: str = '.',
              quiet: bool = False):
    G, root = _load_graph(directory)

    def find_node(term):
        term_l = term.lower()
        scored = sorted(
            [(sum(1 for w in term_l.split()
                  if w in (G.nodes[n].get('label', '') or '').lower()), n)
             for n in G.nodes()],
            reverse=True,
        )
        return scored[0][1] if scored and scored[0][0] > 0 else None

    try:
        import networkx as nx
    except ImportError:
        raise ImportError('networkx required')

    src = find_node(node_a)
    tgt = find_node(node_b)

    if not src or not tgt:
        print(f'Could not find: {node_a!r} or {node_b!r}')
        return

    try:
        path = nx.shortest_path(G, src, tgt)
        print(f'Shortest path ({len(path) - 1} hops):')
        for i, nid in enumerate(path):
            label = G.nodes[nid].get('label', nid)
            if i < len(path) - 1:
                edge = G[nid][path[i + 1]]
                rel = edge.get('relation', '')
                conf = edge.get('confidence', '')
                print(f'  {label} --{rel}--> [{conf}]')
            else:
                print(f'  {label}')
    except nx.NetworkXNoPath:
        print(f'No path between {node_a!r} and {node_b!r}')
    except nx.NodeNotFound as e:
        print(f'Node not found: {e}')


def explain_node(node: str, directory: str = '.', quiet: bool = False):
    G, root = _load_graph(directory)

    term_l = node.lower()
    scored = sorted(
        [(sum(1 for w in term_l.split()
              if w in (G.nodes[n].get('label', '') or '').lower()), n)
         for n in G.nodes()],
        reverse=True,
    )

    if not scored or scored[0][0] == 0:
        print(f'No node matching {node!r}')
        return

    nid = scored[0][1]
    ndata = G.nodes[nid]

    print(f'NODE: {ndata.get("label", nid)}')
    print(f'  type: {ndata.get("file_type", "unknown")}')
    print(f'  source: {ndata.get("source_file", "")}')
    print(f'  degree: {G.degree(nid)}')
    print(f'  community: {ndata.get("community", -1)}')
    print()
    print('CONNECTIONS:')
    for neighbor in list(G.neighbors(nid))[:25]:
        edge = G[nid][neighbor]
        nlabel = G.nodes[neighbor].get('label', neighbor)
        rel = edge.get('relation', '')
        conf = edge.get('confidence', '')
        print(f'  --{rel}--> {nlabel} [{conf}]')
