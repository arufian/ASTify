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
    'defines', 'calls', 'instantiates', 'assigns', 'references', 'resolves_to',
}


def _load_graph(directory: str, question: str | None = None) -> tuple:
    root = Path(directory).resolve()
    graph_path = root / 'astify-out' / 'graph.json'
    database_path = root / 'astify-out' / 'astify.db'
    database_has_graph = False
    if database_path.exists():
        from astify.storage import has_graph

        database_has_graph = has_graph(database_path)

    if not graph_path.exists() and not database_has_graph:
        print('ERROR: No graph found. Run `astify extract .` then `astify build .` first.')
        raise SystemExit(1)

    try:
        import networkx as nx
        from networkx.readwrite import json_graph
    except ImportError:
        raise ImportError('networkx required. pip install networkx')

    if graph_path.exists():
        data = json.loads(graph_path.read_text(encoding='utf-8'))
        graph_meta = data.get('graph', {})
        G = json_graph.node_link_graph(data, edges='links')
    else:
        from astify.storage import load_graph, load_graph_neighborhood

        G = (
            load_graph_neighborhood(database_path, question)
            if question
            else load_graph(database_path)
        )
        graph_meta = G.graph
    if graph_meta.get('schema_version', 1) < 2:
        print(
            'WARNING: Graph predates Tree-sitter symbol extraction. '
            'Run `astify extract .` then `astify build .` to rebuild it.'
        )
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
        'label', 'source_file', 'symbol_kind', 'parser', 'language',
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
    asks_about_tests = 'test' in question_lower
    creation_intent = any(
        word in question_lower
        for word in ('create', 'creates', 'created', 'creating', 'new', 'instantiate')
    )
    scored = []
    for nid, ndata in G.nodes(data=True):
        label = (ndata.get('label', '') or '').lower()
        source = (ndata.get('source_file', '') or '').lower()
        label_tokens = set(_text_tokens(ndata.get('label', '') or ''))
        label_matched = [term for term in terms if term in label]
        source_matched = [
            term for term in terms if term in source and term not in label
        ]
        matched = label_matched + source_matched
        score = 0
        for term in label_matched:
            if term in label_tokens:
                score += 10 + min(len(term), 24)
            elif term in label:
                score += 6
        for term in source_matched:
            if term in source:
                score += 2
        score += len(set(label_matched)) * 5
        score += len(set(source_matched))
        if label_matched and ndata.get('file_type') == 'symbol':
            score += 8
        if label_matched and ndata.get('source_location'):
            score += 2
        if (
            creation_intent
            and label_matched
            and ndata.get('symbol_kind') == 'constructor_call'
        ):
            score += 20
        source_stem = Path(source).stem
        if not asks_about_tests and (
            source_stem.endswith('test')
            or '/tests/' in f'/{source}/'
            or '/test/' in f'/{source}/'
        ):
            score -= 15
        if score > 0:
            scored.append((score, nid))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return [nid for _, nid in scored[:top_k]]


def _edge_priority(edge: dict) -> tuple:
    relation = edge.get('relation', '')
    confidence = edge.get('confidence', '')
    confidence_rank = {
        'EXTRACTED': 0,
        'HEURISTIC': 1,
        'INFERRED': 2,
    }.get(confidence, 3)
    return (
        confidence_rank,
        0 if relation in STRUCTURAL_RELATIONS else 1,
        relation,
    )


def _literal_report(root, question: str, quiet: bool = False) -> bool:
    """Print EXACT source hits for literal parts of the question.

    Returns whether anything was found. The graph indexes labels and symbols,
    not file content, so literal strings (placeholders, UI labels, CJK phrases)
    are invisible to traversal and need a source scan.
    """
    from astify.literal import literal_candidates, literal_search

    terms = literal_candidates(question)
    if not terms:
        if not quiet:
            print('No literal terms in question to scan for.')
        return False
    hits = literal_search(root, terms)
    if not hits:
        if not quiet:
            print(f'Literal scan [EXACT] for {terms}: no source matches.')
        return False
    print(f'Literal matches [EXACT source scan] for {terms}:')
    for hit in hits:
        print(f'  {hit["path"]}:{hit["line"]}: {hit["text"]}')
    return True


def _has_structural_evidence(G, start_nodes, subgraph_edges) -> bool:
    if any(G.nodes[nid].get('file_type') == 'symbol' for nid in start_nodes):
        return True
    return any(
        G[u][v].get('confidence') in ('EXTRACTED', 'HEURISTIC')
        and G[u][v].get('relation') in STRUCTURAL_RELATIONS
        for u, v in subgraph_edges
    )


def query_graph(question: str, mode: str = 'bfs', budget: int = 2000,
                directory: str = '.', quiet: bool = False,
                literal: str = 'auto'):
    G, root = _load_graph(directory, question=question)
    matched = _expand_query_terms(G, question)
    if not matched:
        print('No vocabulary match. Available terms:', _build_vocab(G)[:20], '...')
        if literal != 'never':
            _literal_report(root, question, quiet=quiet)
        return

    if not quiet:
        print(f'Query expanded: {matched}')

    start_nodes = _find_start_nodes(G, matched, question=question)

    if not start_nodes:
        print('No matching nodes found.')
        if literal != 'never':
            _literal_report(root, question, quiet=quiet)
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
            if node in visited or depth > 6 or len(subgraph_nodes) >= 60:
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
                if len(subgraph_nodes) >= 60:
                    break
                neighbors = sorted(
                    G.neighbors(n),
                    key=lambda neighbor: _edge_priority(G[n][neighbor]),
                )
                for neighbor in neighbors[:20]:
                    if neighbor in subgraph_nodes:
                        remember_edge(n, neighbor)
                    if neighbor not in subgraph_nodes:
                        if len(subgraph_nodes) >= 60:
                            break
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
    lines.append('Connections:')
    for u, v in subgraph_edges[:50]:
        edge = G[u][v]
        location = f' at {edge.get("source_location")}' if edge.get('source_location') else ''
        edge_source = edge.get('edge_source', u)
        edge_target = edge.get('edge_target', v)
        lines.append(f'  {G.nodes[edge_source].get("label",edge_source)}'
                     f' --{edge.get("relation","")}'
                     f' [{edge.get("confidence","")}{location}]-->'
                     f' {G.nodes[edge_target].get("label",edge_target)}')
    lines.append('Traversal nodes:')
    for nid in ordered_nodes[:30]:
        d = G.nodes[nid]
        location = f' loc={d.get("source_location")}' if d.get('source_location') else ''
        lines.append(f'  {d.get("label", nid)} [{d.get("file_type","")}'
                     f' src={d.get("source_file","")}{location}]')

    output = '\n'.join(lines)
    if len(output) > char_budget:
        output = output[:char_budget] + \
                 f'\n... truncated at ~{budget} tokens'
    print(output)

    if literal == 'always' or (
        literal == 'auto'
        and not _has_structural_evidence(G, start_nodes, subgraph_edges)
    ):
        if not quiet:
            print()
            print('Graph gave no exact structural match — scanning source text.')
        _literal_report(root, question, quiet=quiet)


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
        if len(path) == 1:
            print(f'  {G.nodes[path[0]].get("label", path[0])}')
        for current, following in zip(path, path[1:]):
            edge = G[current][following]
            rel = edge.get('relation', '')
            conf = edge.get('confidence', '')
            edge_source = edge.get('edge_source', current)
            edge_target = edge.get('edge_target', following)
            source_label = G.nodes[edge_source].get('label', edge_source)
            target_label = G.nodes[edge_target].get('label', edge_target)
            print(f'  {source_label} --{rel}--> {target_label} [{conf}]')
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
        if edge.get('edge_target') == nid:
            print(f'  <--{rel}-- {nlabel} [{conf}]')
        else:
            print(f'  --{rel}--> {nlabel} [{conf}]')
