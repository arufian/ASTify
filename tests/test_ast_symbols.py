import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from astify.build import build_from_semantic
from astify.identifiers import stem_from_path
from astify.query import query_graph
from astify.symbols import extract_code_symbols


class TreeSitterSymbolTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()
        self.apex = self.root / 'ArtifactService.cls'
        self.javascript = self.root / 'ArtifactPanel.js'
        self.apex.write_text(
            'public class ArtifactService {\n'
            '  public static void attachArtifact(Id targetId) {\n'
            '    ArtifactLink link = new ArtifactLink('
            'TargetEntityId = targetId);\n'
            '    Database.insert(link);\n'
            '  }\n'
            '}\n',
            encoding='utf-8',
        )
        self.javascript.write_text(
            "import attachArtifact from "
            "'@salesforce/apex/ArtifactService.attachArtifact';\n"
            'export default class ArtifactPanel {\n'
            '  handleSave() {\n'
            '    return attachArtifact({ targetId: this.recordId });\n'
            '  }\n'
            '}\n',
            encoding='utf-8',
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def extract(self):
        files = [self.apex, self.javascript]
        texts = {
            str(path): path.read_text(encoding='utf-8') for path in files
        }
        return extract_code_symbols(files, self.root, texts)

    def test_apex_and_javascript_use_real_ast_nodes(self):
        nodes, edges = self.extract()
        by_label = {node['label']: node for node in nodes}

        self.assertEqual(by_label['ArtifactService']['parser'], 'tree-sitter')
        self.assertEqual(by_label['attachArtifact']['language'], 'apex')
        self.assertEqual(by_label['handleSave']['language'], 'javascript')
        self.assertEqual(by_label['new ArtifactLink']['source_location'], 'line 3:25')
        self.assertEqual(
            by_label['TargetEntityId assignment']['source_location'],
            'line 3:42',
        )
        self.assertEqual(
            by_label['call Database.insert']['source_location'], 'line 4:5'
        )
        self.assertTrue(all(edge['confidence'] == 'EXTRACTED' for edge in edges))

    def test_salesforce_import_resolves_cross_file_call(self):
        nodes, edges = self.extract()
        by_label = {node['label']: node for node in nodes}
        call_id = by_label['call attachArtifact']['id']
        method_id = by_label['attachArtifact']['id']

        resolution = [
            edge for edge in edges
            if edge['source'] == call_id
            and edge['target'] == method_id
            and edge['relation'] == 'resolves_to'
        ]

        self.assertEqual(len(resolution), 1)
        self.assertEqual(resolution[0]['confidence'], 'EXTRACTED')
        self.assertEqual(resolution[0]['source_location'], 'line 4:12')

    def test_query_preserves_call_direction(self):
        nodes, edges = self.extract()
        for path in (self.apex, self.javascript):
            nodes.append({
                'id': stem_from_path(path, self.root),
                'label': path.name,
                'file_type': 'code',
                'source_file': path.name,
                'source_location': None,
            })
        graph, _ = build_from_semantic({
            'nodes': nodes,
            'edges': edges,
            'schema_version': 2,
            'structural_parser': 'tree-sitter',
        })
        out = self.root / 'astify-out'
        out.mkdir()
        (out / 'graph.json').write_text(json.dumps(graph), encoding='utf-8')

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            query_graph('who calls attachArtifact', directory=str(self.root))

        output = stdout.getvalue()
        self.assertIn('handleSave --calls [EXTRACTED at line 4:12]-->', output)
        self.assertIn(
            'call attachArtifact --resolves_to [EXTRACTED at line 4:12]-->'
            ' attachArtifact',
            output,
        )

    def test_unsupported_language_fallback_is_labeled_heuristic(self):
        source = self.root / 'worker.rb'
        source.write_text(
            'def process_item(value)\n'
            '  Helper.run(value)\n'
            'end\n',
            encoding='utf-8',
        )

        nodes, edges = extract_code_symbols(
            [source], self.root, {str(source): source.read_text(encoding='utf-8')}
        )

        self.assertTrue(any(node.get('parser') == 'heuristic' for node in nodes))
        self.assertTrue(edges)
        self.assertTrue(all(edge['confidence'] == 'HEURISTIC' for edge in edges))


if __name__ == '__main__':
    unittest.main()
