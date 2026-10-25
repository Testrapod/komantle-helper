import copy
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import requests

from komantle_helper import core
from komantle_helper.data import fetch_round


SAMPLE = {"key": "사과", "top_scores": [[1, "과일", .5125], [1000, "까치", .12]]}


def response(data=None, status=200):
    result = Mock(status_code=status)
    result.json.return_value = copy.deepcopy(SAMPLE if data is None else data)
    return result


def analysis_module(tokenizer):
    """선택 설치인 KoNLPy 없이도 분석기 경계의 단위 테스트를 실행한다."""
    module = ModuleType('konlpy.tag')
    module.Okt = tokenizer
    return patch.dict(sys.modules, {'konlpy': ModuleType('konlpy'), 'konlpy.tag': module})


class WordTests(unittest.TestCase):
    def tearDown(self):
        core.get_tokenizer.cache_clear()

    def test_initial_consonants_and_length(self):
        word = core.Word("까치 한글A1!")
        self.assertEqual(word.initial_consonant, "ㄲㅊㅎㄱ")
        self.assertEqual(word.length, 8)

    def test_pos_is_lazy_and_cached(self):
        with patch("komantle_helper.core.get_tokenizer") as tokenizer:
            tokenizer.return_value.pos.return_value = [("사과", "Noun")]
            word = core.Word("사과")
            tokenizer.assert_not_called()
            self.assertEqual(word.pos, "명사")
            self.assertEqual(word.pos, "명사")
            tokenizer.return_value.pos.assert_called_once_with("사과")

    def test_pos_mapping_and_split_words(self):
        with patch("komantle_helper.core.get_tokenizer") as tokenizer:
            for tag, expected in [("Noun", "명사"), ("Verb", "동사"), ("Adjective", "형용사"), ("Adverb", "부사"), ("Josa", "기타")]:
                with self.subTest(tag=tag):
                    tokenizer.return_value.pos.return_value = [("단어", tag)]
                    self.assertEqual(core.Word("단어").pos, expected)
            tokenizer.return_value.pos.return_value = [("단", "Noun"), ("어", "Josa")]
            self.assertEqual(core.Word("단어").pos, "기타")

    def test_tokenizer_is_shared(self):
        okt = Mock()
        with analysis_module(okt):
            self.assertIs(core.get_tokenizer(), core.get_tokenizer())
            okt.assert_called_once()

    def test_missing_java_has_actionable_error(self):
        with analysis_module(Mock(side_effect=ValueError("JVM not found"))):
            with self.assertRaisesRegex(core.KomantleError, "JAVA_HOME"):
                core.Word("사과").pos


class UpstreamRoundTests(unittest.TestCase):
    def setUp(self):
        self.get = patch("komantle_helper.data.requests.get", return_value=response()).start()
        self.addCleanup(patch.stopall)

    def test_load_and_all_hint_types(self):
        manager = fetch_round(10)
        self.get.assert_called_once_with(f"{core.KOMANTLE_URL}/10", timeout=15)
        self.assertEqual(len(manager.word_list), 3)
        self.assertEqual(manager.get_word(0), "사과")
        self.assertEqual(manager.get_initial_consonant(1000), "ㄲㅊ")
        self.assertEqual(manager.get_length(1), 2)
        self.assertEqual(manager.get_similarity(0), 100.0)
        self.assertAlmostEqual(manager.get_similarity(1), 51.25)
        with patch.object(core.Word, "_get_pos", return_value="명사"):
            self.assertEqual(manager.get_pos(1), "명사")

    def test_instances_do_not_share_words(self):
        first = fetch_round(1)
        self.get.return_value = response({"key": "포도", "top_scores": []})
        second = fetch_round(2)
        self.assertEqual(first.get_word(0), "사과")
        self.assertEqual(second.get_word(0), "포도")
        self.assertEqual(len(first.word_list), 3)
        self.assertEqual(len(second.word_list), 1)

    def test_loading_does_not_start_java(self):
        with patch("komantle_helper.core.get_tokenizer", side_effect=AssertionError("Unexpected JVM startup")):
            self.assertEqual(fetch_round(1).get_word(0), "사과")

    def test_character_uses_requested_index(self):
        manager = fetch_round(1)
        self.assertEqual(manager.get_one_character(0, 0), "사")
        self.assertEqual(manager.get_one_character(0, 1), "과")
        for index in (-1, 2, "0", True):
            with self.subTest(index=index), self.assertRaises(core.KomantleError):
                manager.get_one_character(0, index)

    def test_missing_and_invalid_ranks(self):
        manager = fetch_round(1)
        for rank in (-1, 2, 1001, "1", True):
            with self.subTest(rank=rank), self.assertRaises(core.KomantleError):
                manager.get_word(rank)

    def test_invalid_rounds_do_not_request_server(self):
        for number in (-1, "1", True):
            with self.subTest(number=number), self.assertRaises(core.KomantleError):
                fetch_round(number)
        self.get.assert_not_called()

    def test_unavailable_round(self):
        self.get.return_value = response(status=404)
        with self.assertRaisesRegex(core.KomantleError, "찾을 수 없습니다"):
            fetch_round(1)

    def test_restricted_round_explains_server_limit(self):
        description = "그저께부터 내일까지만 확인할 수 있습니다."
        self.get.return_value = response({"detail": {"description": description}}, status=422)
        with self.assertRaisesRegex(core.KomantleError, description):
            fetch_round(1)

    def test_restricted_round_handles_unexpected_error_body(self):
        self.get.return_value = response(status=422)
        self.get.return_value.json.side_effect = ValueError("Not JSON")
        with self.assertRaisesRegex(core.KomantleError, "조회할 수 없습니다"):
            fetch_round(1)
        self.get.return_value.json.side_effect = None
        for payload in ([], {"detail": "error"}, {"detail": {"description": None}}):
            self.get.return_value.json.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(core.KomantleError):
                fetch_round(1)

    def test_connection_errors(self):
        for error in (requests.Timeout(), requests.ConnectionError()):
            self.get.side_effect = error
            with self.subTest(error=type(error).__name__), self.assertRaisesRegex(core.KomantleError, "연결"):
                fetch_round(1)

    def test_http_error(self):
        self.get.return_value.raise_for_status.side_effect = requests.HTTPError("503")
        with self.assertRaises(core.KomantleError):
            fetch_round(1)

    def test_invalid_json(self):
        self.get.return_value.json.side_effect = ValueError("Invalid JSON")
        with self.assertRaisesRegex(core.KomantleError, "응답 형식"):
            fetch_round(1)

    def test_malformed_payloads(self):
        payloads = [
            {}, [], {"key": None, "top_scores": []}, {"key": "", "top_scores": []},
            {"key": "사과", "top_scores": None},
        ]
        for scores in ([[1]], [[0, "과일", 1]], [[1001, "과일", 1]],
                       [[1, "과일", 1], [1, "포도", 2]], [[1, None, 1]],
                       [[1, "과일", "oops"]], [[1, "과일", float("nan")]],
                       [[1, "과일", float("inf")]], [[1, "과일", 1.01]], [[1, "과일", -1.01]]):
            payloads.append({"key": "사과", "top_scores": scores})
        for payload in payloads:
            self.get.return_value = response(payload)
            with self.subTest(payload=payload), self.assertRaisesRegex(core.KomantleError, "응답 형식"):
                fetch_round(1)
