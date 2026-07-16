import unittest

from astify.cli import _normalize_argv


class CliTests(unittest.TestCase):
    def test_bare_directory_runs_full_pipeline(self):
        self.assertEqual(_normalize_argv(['/tmp/project']), ['run', '/tmp/project'])

    def test_explicit_subcommand_is_unchanged(self):
        self.assertEqual(
            _normalize_argv(['query', 'where is Widget']),
            ['query', 'where is Widget'],
        )

    def test_options_are_unchanged(self):
        self.assertEqual(_normalize_argv(['--version']), ['--version'])


if __name__ == '__main__':
    unittest.main()
