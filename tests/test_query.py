import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

from astify.query import _expand_query_terms, _find_start_nodes, query_graph


class QueryTests(unittest.TestCase):
    def build_graph(self):
        graph = nx.Graph()
        graph.graph.update({
            'schema_version': 2,
            'structural_parser': 'tree-sitter',
        })
        graph.add_node(
            'file',
            label='ArtifactService.cls',
            file_type='code',
            source_file='src/classes/ArtifactService.cls',
        )
        graph.add_node(
            'method',
            label='attachArtifact',
            file_type='symbol',
            symbol_kind='method',
            source_file='src/classes/ArtifactService.cls',
            source_location='line 2',
        )
        graph.add_node(
            'constructor',
            label='new ArtifactLink',
            file_type='symbol',
            symbol_kind='constructor_call',
            source_file='src/classes/ArtifactService.cls',
            source_location='line 3',
        )
        graph.add_node(
            'assignment',
            label='TargetEntityId assignment',
            file_type='symbol',
            symbol_kind='assignment',
            source_file='src/classes/ArtifactService.cls',
            source_location='line 4',
        )
        graph.add_edge(
            'file', 'method', relation='defines', confidence='EXTRACTED',
            source_location='line 2',
        )
        graph.add_edge(
            'method', 'constructor', relation='instantiates',
            confidence='EXTRACTED', source_location='line 3',
        )
        graph.add_edge(
            'method', 'assignment', relation='assigns', confidence='EXTRACTED',
            source_location='line 4',
        )
        return graph

    def test_expansion_keeps_technical_identifiers_and_drops_noise(self):
        graph = self.build_graph()

        terms = _expand_query_terms(
            graph,
            'Which exact line creates ArtifactLink using TargetEntityId?',
        )

        self.assertIn('artifactlink', terms)
        self.assertIn('targetentityid', terms)
        self.assertNotIn('artifact', terms)
        self.assertNotIn('entity', terms)
        self.assertNotIn('which', terms)
        self.assertNotIn('exact', terms)
        self.assertNotIn('line', terms)

    def test_symbol_nodes_rank_before_filename_only_match(self):
        graph = self.build_graph()
        terms = _expand_query_terms(graph, 'ArtifactLink TargetEntityId')

        starts = _find_start_nodes(graph, terms)

        self.assertEqual(set(starts[:2]), {'constructor', 'assignment'})
        self.assertNotEqual(starts[0], 'file')

    def test_creation_intent_prioritizes_constructor_occurrence(self):
        graph = self.build_graph()
        terms = _expand_query_terms(graph, 'create ArtifactLink TargetEntityId')

        starts = _find_start_nodes(
            graph, terms, question='create ArtifactLink using TargetEntityId'
        )

        self.assertEqual(starts[0], 'constructor')

    def test_production_symbol_ranks_before_same_test_symbol(self):
        graph = self.build_graph()
        graph.add_node(
            'test_constructor',
            label='new ArtifactLink',
            file_type='symbol',
            symbol_kind='constructor_call',
            source_file='src/classes/ArtifactServiceTest.cls',
            source_location='line 20:9',
        )
        terms = _expand_query_terms(graph, 'where is ArtifactLink created')

        starts = _find_start_nodes(
            graph, terms, question='where is ArtifactLink created'
        )

        self.assertLess(starts.index('constructor'), starts.index('test_constructor'))

    def test_query_prints_direct_symbol_locations_and_structural_edges(self):
        graph = self.build_graph()
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir) / 'astify-out'
            out.mkdir()
            data = json_graph.node_link_data(graph, edges='links')
            (out / 'graph.json').write_text(json.dumps(data), encoding='utf-8')
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                query_graph(
                    'Which exact line creates ArtifactLink using TargetEntityId?',
                    directory=tempdir,
                )

        output = stdout.getvalue()
        expansion_line = output.splitlines()[0]
        self.assertIn("'artifactlink'", expansion_line)
        self.assertIn("'targetentityid'", expansion_line)
        self.assertIn('new ArtifactLink [symbol', output)
        self.assertIn('loc=line 3', output)
        self.assertIn('--instantiates [EXTRACTED at line 3]-->', output)

    def test_query_warns_when_graph_predates_ast_schema(self):
        graph = self.build_graph()
        graph.graph.clear()
        with tempfile.TemporaryDirectory() as tempdir:
            out = Path(tempdir) / 'astify-out'
            out.mkdir()
            data = json_graph.node_link_data(graph, edges='links')
            (out / 'graph.json').write_text(json.dumps(data), encoding='utf-8')
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                query_graph('ArtifactLink', directory=tempdir)

        self.assertIn('predates Tree-sitter symbol extraction', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
