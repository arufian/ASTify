import tempfile
import unittest
from pathlib import Path

from astify.detect import SYMBOL_CODE_EXTS, detect_all, detect_content_files
from astify.extract import build_nodes, detect_files


class FileDetectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()

    def tearDown(self):
        self.tempdir.cleanup()

    def write(self, relative_path: str, content: str | bytes) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding='utf-8')
        return path.resolve()

    def test_extracts_code_metadata_and_unknown_text_extensions(self):
        xml = self.write(
            'src/metadata/Sample_Component.config-meta.xml',
            '<Component><label>Sample Component</label></Component>',
        )
        yaml_file = self.write('config/workflow.yaml', 'steps:\n  - extract\n')
        apex = self.write('src/classes/Example.cls',
                          'public class Example {}\n')
        unknown = self.write('rules/pipeline.customlang', 'process sample_data\n')
        extensionless = self.write('Makefile', 'test:\n\tpython -m unittest\n')
        binary = self.write('assets/blob.customlang', b'\x00\x01\x02\xff')

        found = detect_content_files(self.root)

        self.assertEqual(
            set(found), {xml, yaml_file, apex, unknown, extensionless}
        )
        self.assertNotIn(binary, found)
        self.assertEqual(set(detect_files(self.root)), set(found))

    def test_detect_summary_has_no_code_document_duplicates(self):
        xml = self.write('metadata/item.xml', '<item>value</item>')
        markdown = self.write('docs/design.md', '# Design\n')
        unknown = self.write('config/tool.rules', 'allow = true\n')

        summary = detect_all(self.root)

        self.assertEqual(summary['total_files'], 3)
        self.assertEqual(summary['code_files'], 1)
        self.assertEqual(summary['doc_files'], 2)
        self.assertEqual(summary['files']['code'], [str(xml)])
        self.assertEqual(
            set(summary['files']['document']), {str(markdown), str(unknown)}
        )

    def test_file_node_preserves_exact_source_path_and_filename(self):
        xml = self.write(
            'src/metadata/Sample_Component.config-meta.xml',
            '<Component/>',
        )

        nodes = build_nodes([xml], self.root, {}, {}, {})

        self.assertEqual(len(nodes), 1)
        self.assertEqual(
            nodes[0]['source_file'],
            'src/metadata/Sample_Component.config-meta.xml',
        )
        self.assertEqual(
            nodes[0]['label'],
            'Sample_Component.config-meta.xml',
        )
        self.assertEqual(nodes[0]['file_type'], 'code')

    def test_metadata_formats_are_not_programming_symbol_inputs(self):
        self.assertNotIn('.xml', SYMBOL_CODE_EXTS)
        self.assertNotIn('.yaml', SYMBOL_CODE_EXTS)
        self.assertIn('.cls', SYMBOL_CODE_EXTS)

    def test_utf8_sample_ending_mid_character_remains_text(self):
        source = self.write(
            'src/LargeSource.cls',
            ('a' * 8191) + '界' + '\npublic class LargeSource {}\n',
        )

        found = detect_content_files(self.root)

        self.assertIn(source, found)


if __name__ == '__main__':
    unittest.main()
