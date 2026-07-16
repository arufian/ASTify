import tempfile
import unittest
from pathlib import Path

from astify.symbols import extract_code_symbols


class SymbolExtractionTests(unittest.TestCase):
    def test_extracts_methods_constructors_assignments_and_calls(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            source = root / 'src' / 'classes' / 'ArtifactService.cls'
            source.parent.mkdir(parents=True)
            source.write_text(
                'public class ArtifactService {\n'
                '    private static void attachArtifact(Id targetId) {\n'
                '        ArtifactLink link = new ArtifactLink(\n'
                '            TargetEntityId = targetId\n'
                '        );\n'
                '        Database.insert(link);\n'
                '    }\n'
                '}\n',
                encoding='utf-8',
            )
            source = source.resolve()

            nodes, edges = extract_code_symbols(
                [source], root, {str(source): source.read_text(encoding='utf-8')}
            )

        by_label = {node['label']: node for node in nodes}
        self.assertEqual(by_label['attachArtifact']['symbol_kind'], 'method')
        self.assertEqual(by_label['attachArtifact']['source_location'], 'line 2')
        self.assertEqual(by_label['new ArtifactLink']['source_location'], 'line 3:29')
        self.assertEqual(
            by_label['TargetEntityId assignment']['source_location'], 'line 4:13'
        )

        structural = {
            (edge['relation'], edge['source_location'], edge['confidence'])
            for edge in edges
        }
        self.assertIn(('instantiates', 'line 3:29', 'EXTRACTED'), structural)
        self.assertIn(('assigns', 'line 4:13', 'EXTRACTED'), structural)
        self.assertIn(('calls', 'line 6:9', 'EXTRACTED'), structural)

    def test_does_not_treat_equality_as_assignment(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            source = root / 'src' / 'Example.cls'
            source.parent.mkdir(parents=True)
            source.write_text(
                'public class Example {\n'
                '    public Boolean check(Id value) {\n'
                '        return value == null;\n'
                '    }\n'
                '}\n',
                encoding='utf-8',
            )
            source = source.resolve()

            nodes, _ = extract_code_symbols(
                [source], root, {str(source): source.read_text(encoding='utf-8')}
            )

        self.assertFalse(any(node['symbol_kind'] == 'assignment' for node in nodes))

    def test_ignores_symbols_inside_comments_strings_and_minified_files(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir).resolve()
            source = root / 'src' / 'Example.js'
            source.parent.mkdir(parents=True)
            source.write_text(
                '// HiddenCommentSymbol()\n'
                'function visibleCall() {\n'
                '  const message = "HiddenStringSymbol()";\n'
                '  RealDependency.run();\n'
                '}\n',
                encoding='utf-8',
            )
            minified = root / 'src' / 'vendor.min.js'
            minified.write_text('function VendorThing(){VendorCall();}', encoding='utf-8')
            source = source.resolve()
            minified = minified.resolve()

            nodes, _ = extract_code_symbols(
                [source, minified],
                root,
                {
                    str(source): source.read_text(encoding='utf-8'),
                    str(minified): minified.read_text(encoding='utf-8'),
                },
            )

        labels = {node['label'] for node in nodes}
        self.assertIn('visibleCall', labels)
        self.assertIn('call RealDependency.run', labels)
        self.assertNotIn('HiddenCommentSymbol', labels)
        self.assertNotIn('HiddenStringSymbol', labels)
        self.assertNotIn('VendorThing', labels)


if __name__ == '__main__':
    unittest.main()
