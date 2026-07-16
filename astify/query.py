"""Graph query: BFS/DFS traversal, path finding, node explanation."""
import json
import re
from pathlib import Path


STOPWORDS = {
    'about', 'after', 'also', 'and', 'are', 'before', 'between', 'but', 'can',
    'created', 'creates', 'creating', 'does', 'exact', 'file', 'find', 'for',
    'from', 'how', 'into', 'line', 'lines', 'of', 'on', 'or', 'show', 'that',
    'the', 'this', 'through', 'to', 'using', 'what', 'when', 'where', 'which',
    'who', 'why', 'with',
}
STRUCTURAL_RELATIONS = {
    'defines', 'calls', 'instantiates', 'assigns', 'references',
}


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


def _text_tokens(text: str) -> list[str]:
    """Tokenize natural language plus snake_case and CamelCase identifiers."""
    found = []
    seen = set()
    for token in re.findall(r'[^\W\d][\w]*', text, re.UNICODE):
        variants = [token]
        variants.extend(part for part in token.split('_') if part)
        variants.extend(
            re.findall(
                r'[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+',
                token,
            )
        )
        for variant in variants:
            normalized = variant.lower()
            if (
                3 <= len(normalized) <= 80
                and normalized not in STOPWORDS
                and normalized not in seen
            ):
                seen.add(normalized)
                found.append(normalized)
    return found


def _node_search_text(ndata: dict) -> str:
    return ' '.join(str(ndata.get(key, '') or '') for key in (
        'label', 'source_file', 'symbol_kind',
    ))


def _build_vocab(G) -> list[str]:
    """Extract searchable vocabulary from labels, paths, and symbol metadata."""
    vocab = set()
    for _, ndata in G.nodes(data=True):
        vocab.update(_text_tokens(_node_search_text(ndata)))
    return sorted(vocab)


def _expand_query_terms(G, question: str) -> list[str]:
    vocab = set(_build_vocab(G))
    matched = []
    seen = set()
    for raw_token in re.findall(r'[^\W\d][\w]*', question, re.UNICODE):
        variants = _text_tokens(raw_token)
        if not variants:
            continue
        whole = raw_token.lower()
        candidates = [whole] if whole in vocab else variants
        for term in candidates:
            if term in vocab and term not in seen:
                seen.add(term)
                matched.append(term)
    return matched


def _find_start_nodes(G, terms: list[str], top_k: int = 8,
                      question: str = '') -> list:
    question_lower = question.lower()
    creation_intent = any(
        word in question_lower
        for word in ('create', 'creates', 'created', 'creating', 'new', 'instantiate')
    )
    scored = []
    for nid, ndata in G.nodes(data=True):
        label = (ndata.get('label', '') or '').lower()
        source = (ndata.get('source_file', '') or '').lower()
        label_tokens = set(_text_tokens(ndata.get('label', '') or ''))
        matched = [term for term in terms if term in label or term in source]
        score = 0
        for term in matched:
            if term in label_tokens:
                score += 10
            elif term in label:
                score += 6
            if term in source:
                score += 2
        score += len(set(matched)) * 4
        if matched and ndata.get('file_type') == 'symbol':
            score += 8
        if matched and ndata.get('source_location'):
            score += 2
        if creation_intent and ndata.get('symbol_kind') == 'constructor_call':
            score += 20
        if score > 0:
            scored.append((score, nid))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return [nid for _, nid in scored[:top_k]]


def _edge_priority(edge: dict) -> tuple:
    relation = edge.get('relation', '')
    confidence = edge.get('confidence', '')
    return (
        0 if confidence == 'EXTRACTED' else 1,
        0 if relation in STRUCTURAL_RELATIONS else 1,
        relation,
    )


def query_graph(question: str, mode: str = 'bfs', budget: int = 2000,
                directory: str = '.', quiet: bool = False):
    G, root = _load_graph(directory)
    matched = _expand_query_terms(G, question)
    if not matched:
        print('No vocabulary match. Available terms:', _build_vocab(G)[:20], '...')
        return

    if not quiet:
        print(f'Query expanded: {matched}')

    start_nodes = _find_start_nodes(G, matched, question=question)

    if not start_nodes:
        print('No matching nodes found.')
        return

    subgraph_nodes = set(start_nodes)
    ordered_nodes = list(start_nodes)
    subgraph_edges = []
    seen_edges = set()

    def remember_edge(source, target):
        key = tuple(sorted((str(source), str(target))))
        if key not in seen_edges:
            seen_edges.add(key)
            subgraph_edges.append((source, target))

    if mode == 'dfs':
        visited = set()
        stack = [(n, 0) for n in reversed(start_nodes)]
        while stack:
            node, depth = stack.pop()
            if node in visited or depth > 6:
                continue
            visited.add(node)
            if node not in subgraph_nodes:
                subgraph_nodes.add(node)
                ordered_nodes.append(node)
            neighbors = sorted(
                G.neighbors(node),
                key=lambda neighbor: _edge_priority(G[node][neighbor]),
            )
            for neighbor in neighbors[:20]:
                if neighbor in subgraph_nodes:
                    remember_edge(node, neighbor)
                if neighbor not in visited:
                    stack.append((neighbor, depth + 1))
                    remember_edge(node, neighbor)
    else:
        frontier = list(start_nodes)
        for _ in range(2):
            next_frontier = []
            for n in frontier:
                neighbors = sorted(
                    G.neighbors(n),
                    key=lambda neighbor: _edge_priority(G[n][neighbor]),
                )
                for neighbor in neighbors[:20]:
                    if neighbor in subgraph_nodes:
                        remember_edge(n, neighbor)
                    if neighbor not in subgraph_nodes:
                        next_frontier.append(neighbor)
                        ordered_nodes.append(neighbor)
                        subgraph_nodes.add(neighbor)
                        remember_edge(n, neighbor)
            frontier = next_frontier
            if len(subgraph_nodes) >= 60:
                break

    char_budget = budget * 4
    lines = [f'Traversal: {mode.upper()} | {len(subgraph_nodes)} nodes']
    lines.append('Direct matches:')
    for nid in start_nodes:
        d = G.nodes[nid]
        location = f' loc={d.get("source_location")}' if d.get('source_location') else ''
        lines.append(f'  {d.get("label", nid)} [{d.get("file_type","")}'
                     f' src={d.get("source_file","")}{location}]')
    lines.append('Traversal nodes:')
    for nid in ordered_nodes[:30]:
        d = G.nodes[nid]
        location = f' loc={d.get("source_location")}' if d.get('source_location') else ''
        lines.append(f'  {d.get("label", nid)} [{d.get("file_type","")}'
                     f' src={d.get("source_file","")}{location}]')
    for u, v in subgraph_edges[:50]:
        edge = G[u][v]
        location = f' at {edge.get("source_location")}' if edge.get('source_location') else ''
        lines.append(f'  {G.nodes[u].get("label",u)}'
                     f' --{edge.get("relation","")}'
                     f' [{edge.get("confidence","")}{location}]-->'
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
    if ndata.get('source_location'):
        print(f'  location: {ndata["source_location"]}')
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
