from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from komantle_helper.core import Word
from komantle_helper.archive import json_bytes, read_round
from scripts.collect_data import collect_archive, load_archive
from scripts.demo_data import demo_manager
from scripts.migrate_similarity import migrate_archive


class SimilarityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with patch.object(Word, '_get_pos', return_value='명사'):
            collect_archive(self.root, now=datetime(2026, 10, 24, tzinfo=timezone.utc), manager_factory=demo_manager)

    def make_legacy(self):
        manifest = load_archive(self.root)
        for record in manifest['rounds']:
            data = read_round(self.root, record['path'])
            del data['similarity_scale']
            for row in data['words']:
                if row['rank']:
                    row['similarity'] /= 100
            content = json_bytes(data)
            record['path'] = f"rounds/{data['round']}.{hashlib.sha256(content).hexdigest()}.json"
            (self.root / record['path']).write_bytes(content)
        (self.root / 'manifest.json').write_bytes(json_bytes(manifest))
        return manifest

    def test_legacy_archive_is_corrected_once_and_old_files_are_preserved(self):
        legacy = self.make_legacy()
        self.assertEqual(migrate_archive(self.root), [1665, 1666, 1667])
        for old, new in zip(legacy['rounds'], load_archive(self.root)['rounds']):
            self.assertNotEqual(old['path'], new['path'])
            self.assertTrue((self.root / old['path']).is_file())
            data = read_round(self.root, new['path'])
            self.assertEqual(data['similarity_scale'], 100)
            self.assertEqual(data['words'][0]['similarity'], 100)
            self.assertAlmostEqual(data['words'][1]['similarity'], 59.96)
            self.assertEqual(data['collected_at'], json.loads((self.root / old['path']).read_text())['collected_at'])
        before = (self.root / 'manifest.json').read_bytes()
        self.assertEqual(migrate_archive(self.root), [])
        self.assertEqual((self.root / 'manifest.json').read_bytes(), before)

    def test_new_archives_are_already_in_display_units(self):
        before = (self.root / 'manifest.json').read_bytes()
        self.assertEqual(migrate_archive(self.root), [])
        self.assertEqual((self.root / 'manifest.json').read_bytes(), before)

    def test_ambiguous_legacy_scores_fail_without_changing_manifest(self):
        legacy = self.make_legacy()
        record = legacy['rounds'][0]
        data = read_round(self.root, record['path'])
        data['words'][1]['similarity'] = 50
        content = json_bytes(data)
        record['path'] = f"rounds/{data['round']}.{hashlib.sha256(content).hexdigest()}.json"
        (self.root / record['path']).write_bytes(content)
        (self.root / 'manifest.json').write_bytes(json_bytes(legacy))
        before = (self.root / 'manifest.json').read_bytes()
        with self.assertRaises(ValueError):
            migrate_archive(self.root)
        self.assertEqual((self.root / 'manifest.json').read_bytes(), before)
