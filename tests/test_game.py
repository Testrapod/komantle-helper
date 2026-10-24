from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
import main
from game import GameError, GameSession, Guess, normalize_word, run_game, score_upstream
from test_main import response, SAMPLE


class ScoringTests(unittest.TestCase):
    def test_api_rank_and_score_conversion_and_encoded_input(self):
        get = Mock(return_value=response({'guess': '사과', 'sim': .125, 'rank': '1000위 이상'}))
        result = score_upstream(1667, ' 사과 ', request_get=get)
        self.assertEqual(asdict(result), {'word': '사과', 'similarity': 12.5, 'rank': None, 'correct': False})
        self.assertIn('%EC%82%AC%EA%B3%BC', get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs['timeout'], 15)
        for rank, expected in [(1, 1), (1000, 1000), ('정답!', 0)]:
            get.return_value = response({'guess': '사과', 'sim': 1 if expected == 0 else .5, 'rank': rank})
            self.assertEqual(score_upstream(1667, '사과', request_get=get).rank, expected)

    def test_invalid_words_errors_and_corrupt_scores(self):
        for text in ['', '여러 단어', 'a' * 65]:
            with self.assertRaises(GameError):
                normalize_word(text)
        for status in [404, 422, 429]:
            with self.subTest(status=status), self.assertRaises(GameError):
                score_upstream(1, '사과', request_get=Mock(return_value=response(status=status)))
        with self.assertRaises(GameError):
            score_upstream(1, '사과', request_get=Mock(side_effect=requests.Timeout()))
        for payload in [{'guess': '사과', 'sim': float('nan'), 'rank': 1}, {'guess': '사과', 'sim': 0, 'rank': True}, {'guess': '다른단어', 'sim': .5, 'rank': 1}]:
            with self.subTest(payload=payload), self.assertRaises(GameError):
                score_upstream(1, '사과', request_get=Mock(return_value=response(payload)))

    def test_top_scores_and_live_scores_use_the_same_scale(self):
        raw = .2421453297138214
        manager = main.WordManager(1667, request_get=Mock(return_value=response({
            'key': '사과', 'top_scores': [[897, '토마토', raw]],
        })))
        live = score_upstream(1667, '토마토', request_get=Mock(return_value=response({
            'guess': '토마토', 'sim': raw, 'rank': 897,
        })))
        self.assertAlmostEqual(manager.get_similarity(897), 24.21453297138214)
        with tempfile.TemporaryDirectory() as state:
            cached = GameSession(1667, manager, state_dir=state).submit('토마토')
        self.assertEqual(cached, live)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch('main.requests.get', return_value=response()):
            self.manager = main.WordManager(10)
        self.scorer = Mock(return_value=Guess('바다', 8.5, None, False))

    def session(self, number=10):
        return GameSession(number, self.manager, state_dir=self.temp.name, scorer=self.scorer)

    def test_cached_scoring_duplicate_win_and_resume(self):
        game = self.session()
        self.assertEqual(game.submit('과일').rank, 1)
        self.scorer.assert_not_called()
        with self.assertRaises(GameError):
            game.submit('과일')
        self.assertEqual(len(game.guesses), 1)
        game.submit('사과')
        self.assertTrue(game.won)
        restored = self.session()
        self.assertTrue(restored.won)
        self.assertEqual(len(restored.guesses), 2)
        self.assertFalse(self.session(11).won)
        with self.assertRaises(GameError):
            restored.submit('바다')

    def test_unknown_word_uses_api_and_failure_does_not_count(self):
        game = self.session()
        self.assertEqual(game.submit('바다').similarity, 8.5)
        self.scorer.assert_called_once_with(10, '바다')
        self.scorer.side_effect = GameError('서버 오류')
        with self.assertRaises(GameError):
            game.submit('나무')
        self.assertEqual(len(game.guesses), 1)

    def test_giveup_persists_and_corrupt_storage_recovers(self):
        game = self.session()
        self.assertEqual(game.give_up(), '사과')
        self.assertTrue(self.session().given_up)
        game.path.write_text('{broken')
        restored = self.session()
        self.assertTrue(restored.storage_warning)
        self.assertFalse(restored.given_up)

    def test_storage_failure_keeps_playable_session(self):
        game = self.session()
        with patch('game.os.replace', side_effect=OSError('full')):
            game.submit('과일')
        self.assertEqual(len(game.guesses), 1)
        self.assertTrue(game.storage_warning)

    def test_restore_corrects_cached_scores_without_changing_live_scores_or_attempts(self):
        game = self.session()
        game.submit('과일')
        game.submit('바다')
        saved = json.loads(game.path.read_text())
        saved['guesses'][0]['similarity'] = .5125
        saved['guesses'][1]['similarity'] = .25
        saved['given_up'] = True
        game.path.write_text(json.dumps(saved))
        restored = self.session()
        self.assertAlmostEqual(restored.guesses[0].similarity, 51.25)
        self.assertEqual(restored.guesses[1].similarity, .25)
        self.assertEqual(len(restored.guesses), 2)
        self.assertTrue(restored.given_up)
        self.assertAlmostEqual(json.loads(game.path.read_text())['guesses'][0]['similarity'], 51.25)

    def test_cli_guess_history_and_win(self):
        with patch('builtins.input', side_effect=['과일', '/기록', '과일', '사과']), patch('sys.stdout', new_callable=io.StringIO) as output:
            run_game(10, self.manager, state_dir=self.temp.name)
        self.assertIn('이미 입력한 단어', output.getvalue())
        self.assertIn('2번 만에 정답', output.getvalue())

    def test_cli_play_entrypoint_and_giveup_cancel(self):
        with patch('main.requests.get', return_value=response()), patch('builtins.input', side_effect=['/포기', 'n', '/돌아가기']), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(main.main(['--play', '--round', '10', '--state-dir', self.temp.name]), 0)
        self.assertFalse(self.session().given_up)
