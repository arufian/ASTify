"""SQLite persistence for semantic extraction and built graphs."""
import json
import re
import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_nodes (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_edges_source
    ON semantic_edges(source);
CREATE INDEX IF NOT EXISTS idx_semantic_edges_target
    ON semantic_edges(target);
CREATE TABLE IF NOT EXISTS hyperedges (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target);
"""

QUERY_STOPWORDS = {
    'about', 'after', 'and', 'are', 'before', 'between', 'can', 'does', 'exact',
    'find', 'for', 'from', 'how', 'into', 'line', 'show', 'that', 'the', 'this',
    'through', 'using', 'what', 'when', 'where', 'which', 'who', 'why', 'with',
}


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    return connection


def save_semantic(path: Path, semantic: dict) -> None:
    """Replace semantic extraction tables in one transaction."""
    with _connect(path) as connection:
        connection.execute('DELETE FROM semantic_nodes')
        connection.execute('DELETE FROM semantic_edges')
        connection.execute('DELETE FROM hyperedges')
        connection.execute('DELETE FROM graph_nodes')
        connection.execute('DELETE FROM graph_edges')
        connection.executemany(
            'INSERT INTO semantic_nodes(id, data) VALUES (?, ?)',
            (
                (
                    str(node['id']),
                    json.dumps(node, ensure_ascii=False, separators=(',', ':')),
                )
                for node in semantic.get('nodes', [])
            ),
        )
        connection.executemany(
            """
            INSERT INTO semantic_edges(source, target, relation, data)
            VALUES (?, ?, ?, ?)
            """,
            (
                (
                    str(edge['source']),
                    str(edge['target']),
                    str(edge.get('relation', 'relates_to')),
                    json.dumps(edge, ensure_ascii=False, separators=(',', ':')),
                )
                for edge in semantic.get('edges', [])
            ),
        )
        connection.executemany(
            'INSERT INTO hyperedges(id, data) VALUES (?, ?)',
            (
                (
                    str(edge['id']),
                    json.dumps(edge, ensure_ascii=False, separators=(',', ':')),
                )
                for edge in semantic.get('hyperedges', [])
            ),
        )
        metadata = {
            'schema_version': semantic.get('schema_version', 1),
            'structural_parser': semantic.get('structural_parser'),
            'input_tokens': semantic.get('input_tokens', 0),
            'output_tokens': semantic.get('output_tokens', 0),
        }
        connection.execute(
            'INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)',
            ('semantic', json.dumps(metadata, ensure_ascii=False)),
        )


def load_semantic(path: Path) -> dict:
    """Load semantic extraction from SQLite."""
    with _connect(path) as connection:
        nodes = [
            json.loads(row[0])
            for row in connection.execute(
                'SELECT data FROM semantic_nodes ORDER BY rowid'
            )
        ]
        edges = [
            json.loads(row[0])
            for row in connection.execute(
                'SELECT data FROM semantic_edges ORDER BY edge_id'
            )
        ]
        hyperedges = [
            json.loads(row[0])
            for row in connection.execute(
                'SELECT data FROM hyperedges ORDER BY rowid'
            )
        ]
        row = connection.execute(
            'SELECT value FROM metadata WHERE key = ?', ('semantic',)
        ).fetchone()
    metadata = json.loads(row[0]) if row else {}
    return {
        'nodes': nodes,
        'edges': edges,
        'hyperedges': hyperedges,
        **metadata,
    }


def save_graph(path: Path, graph, metadata: dict) -> None:
    """Persist a NetworkX graph without requiring one giant JSON document."""
    with _connect(path) as connection:
        connection.execute('DELETE FROM graph_nodes')
        connection.execute('DELETE FROM graph_edges')
        connection.executemany(
            'INSERT INTO graph_nodes(id, data) VALUES (?, ?)',
            (
                (
                    str(node_id),
                    json.dumps(
                        {'id': node_id, **data},
                        ensure_ascii=False,
                        separators=(',', ':'),
                    ),
                )
                for node_id, data in graph.nodes(data=True)
            ),
        )
        connection.executemany(
            'INSERT INTO graph_edges(source, target, data) VALUES (?, ?, ?)',
            (
                (
                    str(source),
                    str(target),
                    json.dumps(data, ensure_ascii=False, separators=(',', ':')),
                )
                for source, target, data in graph.edges(data=True)
            ),
        )
        connection.execute(
            'INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)',
            ('graph', json.dumps(graph.graph, ensure_ascii=False)),
        )
        connection.execute(
            'INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)',
            ('analysis', json.dumps(metadata, ensure_ascii=False)),
        )


def has_graph(path: Path) -> bool:
    if not path.exists():
        return False
    with _connect(path) as connection:
        row = connection.execute(
            'SELECT 1 FROM graph_nodes LIMIT 1'
        ).fetchone()
    return row is not None


def load_graph(path: Path):
    """Load persisted graph for query operations."""
    import networkx as nx

    graph = nx.Graph()
    with _connect(path) as connection:
        row = connection.execute(
            'SELECT value FROM metadata WHERE key = ?', ('graph',)
        ).fetchone()
        if row:
            graph.graph.update(json.loads(row[0]))
        for node_id, data in connection.execute(
            'SELECT id, data FROM graph_nodes'
        ):
            attributes = json.loads(data)
            attributes.pop('id', None)
            graph.add_node(node_id, **attributes)
        for source, target, data in connection.execute(
            'SELECT source, target, data FROM graph_edges'
        ):
            graph.add_edge(source, target, **json.loads(data))
    return graph


def load_graph_neighborhood(
    path: Path,
    query: str,
    depth: int = 2,
    max_seeds: int = 100,
    max_nodes: int = 5_000,
):
    """Load only matching nodes and a bounded SQLite neighborhood."""
    import networkx as nx

    terms = []
    seen_terms = set()
    for term in re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}', query.lower()):
        if term not in seen_terms and term not in QUERY_STOPWORDS:
            seen_terms.add(term)
            terms.append(term)
    graph = nx.Graph()
    if not terms:
        return graph

    with _connect(path) as connection:
        row = connection.execute(
            'SELECT value FROM metadata WHERE key = ?', ('graph',)
        ).fetchone()
        if row:
            graph.graph.update(json.loads(row[0]))

        predicates = ' OR '.join('lower(data) LIKE ?' for _ in terms)
        score = ' + '.join(
            'CASE WHEN lower(data) LIKE ? THEN 1 ELSE 0 END'
            for _ in terms
        )
        patterns = [f'%{term}%' for term in terms]
        seed_rows = connection.execute(
            f"""
            SELECT id
            FROM graph_nodes
            WHERE {predicates}
            ORDER BY ({score}) DESC
            LIMIT ?
            """,
            patterns + patterns + [max_seeds],
        ).fetchall()
        selected = {row[0] for row in seed_rows}
        frontier = set(selected)
        edge_rows: dict[tuple[str, str], str] = {}

        for _ in range(depth):
            if not frontier or len(selected) >= max_nodes:
                break
            next_frontier = set()
            frontier_list = list(frontier)
            for start in range(0, len(frontier_list), 400):
                chunk = frontier_list[start:start + 400]
                placeholders = ','.join('?' for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT source, target, data
                    FROM graph_edges
                    WHERE source IN ({placeholders})
                       OR target IN ({placeholders})
                    """,
                    chunk + chunk,
                )
                for source, target, data in rows:
                    edge_rows[(source, target)] = data
                    for node_id in (source, target):
                        if node_id not in selected and len(selected) < max_nodes:
                            selected.add(node_id)
                            next_frontier.add(node_id)
            frontier = next_frontier

        node_data = {}
        selected_list = list(selected)
        for start in range(0, len(selected_list), 800):
            chunk = selected_list[start:start + 800]
            placeholders = ','.join('?' for _ in chunk)
            for node_id, data in connection.execute(
                f'SELECT id, data FROM graph_nodes WHERE id IN ({placeholders})',
                chunk,
            ):
                node_data[node_id] = json.loads(data)

    for node_id, data in node_data.items():
        data.pop('id', None)
        graph.add_node(node_id, **data)
    for (source, target), data in edge_rows.items():
        if source in graph and target in graph:
            graph.add_edge(source, target, **json.loads(data))
    graph.graph['partial'] = True
    return graph
