import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from main import Word, get_round_date, get_today_round
from scripts.collect_data import collect_archive, export_round, load_archive, read_round, validate_round
from scripts.demo_data import demo_manager
from scripts.build_site import build_site
from scripts.publish_state import publication_state

NOW = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'archive'
        self.pos = patch.object(Word, '_get_pos', return_value='명사')
        self.pos.start()
        self.addCleanup(self.pos.stop)

    def collect(self, **kwargs):
        return collect_archive(self.root, now=NOW, manager_factory=demo_manager, **kwargs)

    def test_korean_date_boundary(self):
        self.assertEqual(get_today_round(NOW), 1667)
        self.assertEqual(get_round_date(1667).isoformat(), '2026-10-24')
        self.assertEqual(get_today_round(datetime(2026, 10, 23, 14, 59, tzinfo=timezone.utc)), 1666)
        self.assertEqual(get_today_round(datetime(2026, 10, 23, 15, tzinfo=timezone.utc)), 1667)
        with self.assertRaises(ValueError):
            get_today_round(datetime(2026, 10, 24))

    def test_collect_keep_history_and_idempotence(self):
        self.assertEqual(self.collect()['saved_rounds'], [1665, 1666, 1667])
        before = (self.root / 'manifest.json').read_bytes()
        result = self.collect()
        self.assertEqual(result['saved_rounds'], [])
        self.assertEqual((self.root / 'manifest.json').read_bytes(), before)
        later = datetime(2026, 10, 25, 1, tzinfo=timezone.utc)
        collect_archive(self.root, now=later, manager_factory=demo_manager)
        self.assertEqual([r['round'] for r in load_archive(self.root, 1668)['rounds']], [1665, 1666, 1667, 1668])

    def test_partial_success_is_preserved(self):
        def factory(number):
            if number == 1667:
                raise RuntimeError('analysis failed')
            return demo_manager(number)
        result = collect_archive(self.root, now=NOW, manager_factory=factory)
        self.assertFalse(result['today_available'])
        self.assertEqual(result['saved_rounds'], [1665, 1666])
        self.assertEqual(list(result['failed_rounds']), ['1667'])
        self.assertEqual(len(load_archive(self.root, 1667)['rounds']), 2)
        self.assertEqual(self.collect()['saved_rounds'], [1667])

    def test_incomplete_and_malformed_rounds_rejected(self):
        data = export_round(demo_manager(1667), 1667, NOW)
        for mutate in (
            lambda d: d['words'].pop(),
            lambda d: d['words'][1].update(rank=0),
            lambda d: d['words'][1].update(similarity=float('nan')),
            lambda d: d['words'][1].update(pos='unknown'),
            lambda d: d['words'][1].update(word=''),
            lambda d: d['words'][1].update(length=True),
            lambda d: d.update(date='2026-10-23'),
            lambda d: d.update(round=1668),
        ):
            value = copy.deepcopy(data)
            mutate(value)
            with self.assertRaises(ValueError):
                validate_round(value, 1667)

    def test_failed_force_keeps_original_and_future_is_rejected(self):
        self.collect()
        before = (self.root / 'manifest.json').read_bytes()
        collect_archive(self.root, now=NOW, force_round=1667,
                        manager_factory=lambda n: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual((self.root / 'manifest.json').read_bytes(), before)
        with self.assertRaises(ValueError):
            self.collect(force_round=1668)

    def test_hash_and_path_validation(self):
        self.collect()
        record = load_archive(self.root, 1667)['rounds'][0]
        with self.assertRaises(ValueError):
            read_round(self.root, '../manifest.json', 1667)
        (self.root / record['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, '해시'):
            load_archive(self.root, 1667)

    def test_nonempty_broken_archive_is_not_reinitialized(self):
        self.root.mkdir()
        (self.root / 'lost.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.collect()

    def test_force_preserves_old_file_and_build_excludes_operations(self):
        self.collect()
        old = load_archive(self.root, 1667)['rounds'][-1]['path']
        with patch.object(Word, '_get_pos', return_value='기타'):
            self.collect(force_round=1667)
        self.assertTrue((self.root / old).exists())
        self.assertEqual(len(list((self.root / 'rounds').glob('*.json'))), 4)
        (self.root / 'operations.json').write_text('{}')
        output = Path(self.temp.name) / 'site'
        build_site(self.root, output)
        self.assertTrue((output / 'index.html').is_file())
        self.assertTrue((output / 'data' / old).is_file())
        self.assertFalse((output / 'data/operations.json').exists())
        self.assertEqual(len(list((output / 'data/rounds').glob('*.json'))), 4)
        build_site(self.root, output)

    def test_build_rejects_unowned_output(self):
        self.collect()
        output = Path(self.temp.name) / 'important'
        output.mkdir()
        (output / 'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):
            build_site(self.root, output)
        self.assertTrue((output / 'keep.txt').exists())

    def test_failed_deployment_retries_but_success_is_noop(self):
        self.collect()
        with patch('scripts.publish_state.get_today_round', return_value=1667):
            state = publication_state(self.root, 'code-a', scheduled=True)
            self.assertTrue(state['deploy'])
            self.assertTrue(publication_state(self.root, 'code-a', scheduled=True)['deploy'])
            (self.root / 'operations.json').write_text(json.dumps({'code_sha': 'code-a', 'data_digest': state['data_digest']}))
            self.assertFalse(publication_state(self.root, 'code-a', scheduled=True)['deploy'])
            self.assertTrue(publication_state(self.root, 'code-b')['deploy'])


if __name__ == '__main__':
    unittest.main()
