from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.archive_git import git, prepare, save


class ArchiveGitTests(unittest.TestCase):
    def test_bootstrap_save_reload_and_noop_without_changing_main(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote, source = root / 'remote.git', root / 'source'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            subprocess.run(['git', 'init', '-b', 'main', str(source)], check=True, capture_output=True)
            (source / 'README.md').write_text('source code')
            git(source, 'add', '.')
            git(source, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'Initial')
            git(source, 'remote', 'add', 'origin', str(remote))
            git(source, 'push', '-u', 'origin', 'main')
            original = git(source, 'rev-parse', 'HEAD').stdout
            archive = root / 'archive'
            prepare(source, archive)
            self.assertFalse((archive / 'README.md').exists())
            (archive / 'manifest.json').write_text('{}')
            self.assertTrue(save(archive))
            self.assertFalse(save(archive))
            second = root / 'second'
            prepare(source, second)
            self.assertEqual((second / 'manifest.json').read_text(), '{}')
            self.assertEqual(git(source, 'rev-parse', 'HEAD').stdout, original)
            self.assertEqual((source / 'README.md').read_text(), 'source code')


if __name__ == '__main__':
    unittest.main()
