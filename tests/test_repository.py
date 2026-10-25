"""캐시와 공개 아카이브의 신뢰 경계·오프라인 동작."""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from komantle_helper.archive import json_bytes
from komantle_helper.core import KomantleError, Word
from komantle_helper.data import Repository, MANIFEST_URL, validate_manifest
from scripts.collect_data import collect_archive
from scripts.demo_data import demo_manager

NOW = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'archive'
        with patch.object(Word, '_get_pos', return_value='명사'):
            collect_archive(self.archive, now=NOW, manager_factory=demo_manager)
        self.manifest = json.loads((self.archive / 'manifest.json').read_text())
        self.record = self.manifest['rounds'][-1]
        self.content = (self.archive / self.record['path']).read_bytes()
        self.get = Mock()
        self.repository = Repository(cache_dir=self.root / 'cache', request_get=self.get)

    def response(self, *, manifest=False, content=None):
        result = Mock()
        result.json.return_value = copy.deepcopy(self.manifest)
        result.content = self.content if content is None else content
        return result

    def test_local_archive_no_network_or_java(self):
        repository = Repository(archive_dir=self.archive, request_get=self.get)
        with patch('komantle_helper.core.get_tokenizer', side_effect=AssertionError('Java started')):
            data = repository.load(1667)
            self.assertEqual(data.get_pos(0), '명사')
            self.assertEqual(data.get_similarity(1), 59.96)
        self.get.assert_not_called()

    def test_remote_round_is_hash_verified_and_cached_for_offline_use(self):
        self.get.side_effect = [self.response(manifest=True), self.response()]
        data = self.repository.load(1667)
        self.assertEqual(data.source, '공개 아카이브')
        self.assertEqual(self.get.call_args_list[0].args[0], MANIFEST_URL)
        offline = Repository(cache_dir=self.repository.cache_dir, request_get=Mock(side_effect=requests.Timeout()))
        self.assertEqual(offline.load(1667).get_word(0), '사과')
        self.assertEqual(offline.load(1667).source, '아카이브 캐시')

    def test_hash_mismatch_is_not_cached(self):
        self.get.side_effect = [self.response(manifest=True), self.response(content=b'{}')]
        with self.assertRaisesRegex(KomantleError, '검증'):
            self.repository.load(1667)
        self.assertFalse((self.repository.cache_dir / self.record['path']).exists())

    def test_refresh_failure_preserves_valid_cache(self):
        self.get.side_effect = [self.response(manifest=True), self.response()]
        self.repository.load(1667)
        self.get.side_effect = requests.Timeout()
        data = self.repository.load(1667, refresh=True)
        self.assertEqual(data.number, 1667)
        self.assertIn('갱신 실패', self.repository.warning)

    def test_missing_local_round_does_not_call_live_api(self):
        repository = Repository(archive_dir=self.archive, request_get=self.get)
        with self.assertRaisesRegex(KomantleError, '없는 회차'):
            repository.load(10)
        self.get.assert_not_called()

    def test_manifest_invalid_dates_order_path_and_count(self):
        for mutate in [
            lambda d: d['rounds'].reverse(),
            lambda d: d['rounds'][0].update(path='../secret.json'),
            lambda d: d['rounds'][0].update(date='2000-01-01'),
            lambda d: d['rounds'][0].update(word_count=1000),
            lambda d: d.update(latest_round=10),
        ]:
            value = copy.deepcopy(self.manifest)
            mutate(value)
            with self.assertRaises((ValueError, KeyError)):
                validate_manifest(value)

    def test_local_corrupt_round_is_rejected(self):
        (self.archive / self.record['path']).write_bytes(b'{}')
        with self.assertRaisesRegex(KomantleError, '손상'):
            Repository(archive_dir=self.archive).load(1667)

    def test_cached_round_damage_is_repaired_from_remote(self):
        self.get.side_effect = [self.response(manifest=True), self.response()]
        self.repository.load(1667)
        (self.repository.cache_dir / self.record['path']).write_bytes(b'broken')
        self.get.side_effect = None
        self.get.return_value = self.response()
        self.assertEqual(self.repository.load(1667).get_word(0), '사과')
        self.assertEqual((self.repository.cache_dir / self.record['path']).read_bytes(), self.content)

    def test_cache_write_failure_does_not_discard_round(self):
        self.get.side_effect = [self.response(manifest=True), self.response()]
        with patch('komantle_helper.data.atomic_write', side_effect=OSError('full')):
            self.assertEqual(self.repository.load(1667).number, 1667)
        self.assertIn('캐시', self.repository.warning)

    def test_legacy_archive_scores_are_normalized_at_boundary(self):
        data = json.loads(self.content)
        del data['similarity_scale']
        for row in data['words']:
            if row['rank']:
                row['similarity'] /= 100
        content = json_bytes(data)
        relative = f'rounds/1667.{hashlib.sha256(content).hexdigest()}.json'
        (self.archive / relative).write_bytes(content)
        self.manifest['rounds'][-1]['path'] = relative
        (self.archive / 'manifest.json').write_bytes(json_bytes(self.manifest))
        result = Repository(archive_dir=self.archive).load(1667)
        self.assertAlmostEqual(result.get_similarity(1), 59.96)

    def test_broken_manifest_and_network_failure_are_actionable(self):
        self.repository.cache_dir.mkdir()
        (self.repository.cache_dir / 'manifest.json').write_text('{}')
        self.get.side_effect = requests.Timeout()
        with self.assertRaisesRegex(KomantleError, '/refresh'):
            self.repository.load_manifest(refresh=True)

    def test_default_selects_today_or_latest_available(self):
        with patch('komantle_helper.data.get_today_round', return_value=1667):
            self.assertEqual(Repository(archive_dir=self.archive).load().number, 1667)
        with patch('komantle_helper.data.get_today_round', return_value=1668):
            self.assertEqual(Repository(archive_dir=self.archive).load().number, 1667)
