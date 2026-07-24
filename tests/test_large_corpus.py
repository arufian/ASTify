import contextlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from astify.build import build_from_semantic, build_graph
from astify.export import export_html
from astify.extract import build_edges, build_nodes
from astify.query import query_graph
from astify.storage import (
    load_graph,
    load_graph_neighborhood,
    load_semantic,
    save_semantic,
)


class LargeCorpusTests(unittest.TestCase):
    def test_500_similar_files_have_bounded_semantic_edges(self):
        root = Path('/tmp/astify-large-edge-test')
        files = [root / f'Class{index}.cls' for index in range(500)]
        embeddings = {
            str(path): np.ones(64, dtype=np.float32)
            for path in files
        }
        keywords = {
            str(path): [('apex service', 0.9)]
            for path in files
        }

        nodes = build_nodes(files, root, keywords, {}, {})
        edges = build_edges(
            files,
            root,
            embeddings,
            keywords,
            {},
            {},
            max_similarity_neighbors=20,
        )

        concept_nodes = [
            node for node in nodes
            if node['id'] == 'concept_keyword_apex_service'
        ]
        similarity_edges = [
            edge for edge in edges
            if edge['relation'] == 'semantically_similar_to'
        ]
        concept_edges = [
            edge for edge in edges
            if edge['relation'] == 'conceptually_related_to'
        ]

        self.assertEqual(len(concept_nodes), 1)
        self.assertEqual(len(concept_edges), 500)
        self.assertLessEqual(len(similarity_edges), 500 * 20)
        self.assertLessEqual(len(edges), 10_500)

    def test_5000_code_file_build_is_bounded_and_sqlite_backed(self):
        file_count = 5_000
        nodes = [
            {
                'id': f'class_{index}',
                'label': f'Class{index}.cls',
                'file_type': 'code',
                'source_file': f'force-app/classes/Class{index}.cls',
            }
            for index in range(file_count)
        ]
        edges = [
            {
                'source': f'class_{index}',
                'target': f'class_{index + 1}',
                'relation': 'semantically_similar_to',
                'confidence': 'INFERRED',
                'confidence_score': 0.8,
            }
            for index in range(file_count - 1)
        ]
        semantic = {
            'nodes': nodes,
            'edges': edges,
            'hyperedges': [],
            'schema_version': 2,
            'structural_parser': 'tree-sitter',
        }

        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / 'astify-out'
            database = output / 'astify.db'
            save_semantic(database, semantic)
            stored_semantic = load_semantic(database)
            started = time.perf_counter()
            with patch('astify.build.FULL_JSON_MAX_NODES', 1_000):
                result = build_graph(
                    tempdir,
                    stored_semantic,
                    quiet=True,
                )
            elapsed = time.perf_counter() - started
            persisted = load_graph(database)
            neighborhood = load_graph_neighborhood(
                database, 'Class2500', max_nodes=100
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                query_graph('Class2500', directory=tempdir)

            self.assertEqual(result['meta']['analysis_mode'], 'sampled')
            self.assertEqual(result['meta']['analysis_nodes'], file_count)
            self.assertEqual(len(load_semantic(database)['nodes']), file_count)
            self.assertIsNone(result['graph'])
            self.assertFalse((output / 'graph.json').exists())
            self.assertTrue((output / 'graph-summary.json').exists())
            self.assertEqual(persisted.number_of_nodes(), file_count)
            self.assertTrue(neighborhood.graph['partial'])
            self.assertLessEqual(neighborhood.number_of_nodes(), 100)
            self.assertTrue(
                any(
                    data.get('label') == 'Class2500.cls'
                    for _, data in neighborhood.nodes(data=True)
                )
            )
            self.assertIn('Class2500.cls', stdout.getvalue())
            self.assertLess(elapsed, 30.0)

    def test_oversized_analysis_uses_community_bridges(self):
        semantic = {
            'nodes': [
                {
                    'id': f'node_{index}',
                    'label': f'Node {index}',
                    'file_type': 'code',
                }
                for index in range(100)
            ],
            'edges': [
                {
                    'source': f'node_{index}',
                    'target': f'node_{index + 1}',
                    'relation': 'calls',
                    'confidence': 'EXTRACTED',
                }
                for index in range(99)
            ],
            'schema_version': 2,
        }

        with (
            patch('astify.build.EXACT_MAX_EDGES', 10),
            patch('astify.build.SAMPLED_MAX_EDGES', 10),
        ):
            _, metadata = build_from_semantic(semantic)

        self.assertEqual(metadata['analysis_mode'], 'community_bridges')

    def test_large_html_uses_aggregated_visualization(self):
        semantic = {
            'nodes': [
                {
                    'id': f'node_{index}',
                    'label': f'Class{index}.cls',
                    'file_type': 'code',
                }
                for index in range(30)
            ],
            'edges': [
                {
                    'source': f'node_{index}',
                    'target': f'node_{index + 1}',
                    'relation': 'calls',
                    'confidence': 'EXTRACTED',
                }
                for index in range(29)
            ],
            'schema_version': 2,
        }
        with tempfile.TemporaryDirectory() as tempdir:
            build_graph(tempdir, semantic, quiet=True)
            with patch('astify.export.HTML_MAX_NODES', 10):
                export_html(tempdir, quiet=True)
            html = Path(tempdir) / 'astify-out' / 'graph.html'

            self.assertTrue(html.exists())
            self.assertIn('cross-community edges', html.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
