import copy
import io
import unittest
from unittest.mock import Mock, patch

import requests

import main


SAMPLE = {"key": "사과", "top_scores": [[1, "과일", .5125], [1000, "까치", .12]]}


def response(data=None, status=200):
    result = Mock(status_code=status)
    result.json.return_value = copy.deepcopy(SAMPLE if data is None else data)
    return result


class WordTests(unittest.TestCase):
    def tearDown(self):
        main.get_tokenizer.cache_clear()

    def test_initial_consonants_and_length(self):
        word = main.Word("까치 한글A1!")
        self.assertEqual(word.initial_consonant, "ㄲㅊㅎㄱ")
        self.assertEqual(word.length, 8)

    def test_pos_is_lazy_and_cached(self):
        with patch("main.get_tokenizer") as tokenizer:
            tokenizer.return_value.pos.return_value = [("사과", "Noun")]
            word = main.Word("사과")
            tokenizer.assert_not_called()
            self.assertEqual(word.pos, "명사")
            self.assertEqual(word.pos, "명사")
            tokenizer.return_value.pos.assert_called_once_with("사과")

    def test_pos_mapping_and_split_words(self):
        with patch("main.get_tokenizer") as tokenizer:
            for tag, expected in [("Noun", "명사"), ("Verb", "동사"), ("Adjective", "형용사"), ("Adverb", "부사"), ("Josa", "기타")]:
                with self.subTest(tag=tag):
                    tokenizer.return_value.pos.return_value = [("단어", tag)]
                    self.assertEqual(main.Word("단어").pos, expected)
            tokenizer.return_value.pos.return_value = [("단", "Noun"), ("어", "Josa")]
            self.assertEqual(main.Word("단어").pos, "기타")

    def test_tokenizer_is_shared(self):
        with patch("main.Okt") as okt:
            self.assertIs(main.get_tokenizer(), main.get_tokenizer())
            okt.assert_called_once()

    def test_missing_java_has_actionable_error(self):
        with patch("main.Okt", side_effect=ValueError("JVM not found")):
            with self.assertRaisesRegex(main.KomantleError, "JAVA_HOME"):
                main.Word("사과").pos


class WordManagerTests(unittest.TestCase):
    def setUp(self):
        self.get = patch("main.requests.get", return_value=response()).start()
        self.addCleanup(patch.stopall)

    def test_load_and_all_hint_types(self):
        manager = main.WordManager(10)
        self.get.assert_called_once_with(f"{main.KOMANTLE_URL}/10", timeout=15)
        self.assertEqual(len(manager.word_list), 3)
        self.assertEqual(manager.get_word(0), "사과")
        self.assertEqual(manager.get_initial_consonant(1000), "ㄲㅊ")
        self.assertEqual(manager.get_length(1), 2)
        self.assertEqual(manager.get_similarity(0), 100.0)
        self.assertAlmostEqual(manager.get_similarity(1), 51.25)
        with patch.object(main.Word, "_get_pos", return_value="명사"):
            self.assertEqual(manager.get_pos(1), "명사")

    def test_instances_do_not_share_words(self):
        first = main.WordManager(1)
        self.get.return_value = response({"key": "포도", "top_scores": []})
        second = main.WordManager(2)
        self.assertEqual(first.get_word(0), "사과")
        self.assertEqual(second.get_word(0), "포도")
        self.assertEqual(len(first.word_list), 3)
        self.assertEqual(len(second.word_list), 1)

    def test_loading_does_not_start_java(self):
        with patch("main.Okt", side_effect=AssertionError("Unexpected JVM startup")):
            self.assertEqual(main.WordManager(1).get_word(0), "사과")

    def test_character_uses_requested_index(self):
        manager = main.WordManager(1)
        self.assertEqual(manager.get_one_character(0, 0), "사")
        self.assertEqual(manager.get_one_character(0, 1), "과")
        for index in (-1, 2, "0", True):
            with self.subTest(index=index), self.assertRaises(main.KomantleError):
                manager.get_one_character(0, index)

    def test_missing_and_invalid_ranks(self):
        manager = main.WordManager(1)
        for rank in (-1, 2, 1001, "1", True):
            with self.subTest(rank=rank), self.assertRaises(main.KomantleError):
                manager.get_word(rank)

    def test_invalid_rounds_do_not_request_server(self):
        for number in (-1, "1", True):
            with self.subTest(number=number), self.assertRaises(main.KomantleError):
                main.WordManager(number)
        self.get.assert_not_called()

    def test_unavailable_round(self):
        self.get.return_value = response(status=404)
        with self.assertRaisesRegex(main.KomantleError, "찾을 수 없습니다"):
            main.WordManager(1)

    def test_restricted_round_explains_server_limit(self):
        description = "그저께부터 내일까지만 확인할 수 있습니다."
        self.get.return_value = response({"detail": {"description": description}}, status=422)
        with self.assertRaisesRegex(main.KomantleError, description):
            main.WordManager(1)

    def test_restricted_round_handles_unexpected_error_body(self):
        self.get.return_value = response(status=422)
        self.get.return_value.json.side_effect = ValueError("Not JSON")
        with self.assertRaisesRegex(main.KomantleError, "조회할 수 없습니다"):
            main.WordManager(1)
        self.get.return_value.json.side_effect = None
        for payload in ([], {"detail": "error"}, {"detail": {"description": None}}):
            self.get.return_value.json.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(main.KomantleError):
                main.WordManager(1)

    def test_connection_errors(self):
        for error in (requests.Timeout(), requests.ConnectionError()):
            self.get.side_effect = error
            with self.subTest(error=type(error).__name__), self.assertRaisesRegex(main.KomantleError, "연결"):
                main.WordManager(1)

    def test_http_error(self):
        self.get.return_value.raise_for_status.side_effect = requests.HTTPError("503")
        with self.assertRaises(main.KomantleError):
            main.WordManager(1)

    def test_invalid_json(self):
        self.get.return_value.json.side_effect = ValueError("Invalid JSON")
        with self.assertRaisesRegex(main.KomantleError, "응답 형식"):
            main.WordManager(1)

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
            with self.subTest(payload=payload), self.assertRaisesRegex(main.KomantleError, "응답 형식"):
                main.WordManager(1)


class CliTests(unittest.TestCase):
    def test_all_menu_options_and_invalid_input(self):
        commands = ["invalid", "2", "bad", "2", "10", "invalid", "1", "-1", "1001", "1", "2", "0", "3", "0", "4", "1", "5", "1000", "Q"]
        with patch("main.requests.get", return_value=response()), \
                patch.object(main.Word, "_get_pos", return_value="명사"), \
                patch("builtins.input", side_effect=commands), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main.main(), 0)
        text = output.getvalue()
        self.assertEqual(text.count("는(은)"), 5)
        self.assertIn("도움이 되셨길 바랍니다", text)

    def test_load_error_returns_failure(self):
        with patch("builtins.input", return_value="1"), \
                patch("main.requests.get", side_effect=requests.Timeout()), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main.main(), 1)

    def test_quit_without_loading(self):
        with patch("builtins.input", return_value="q"), \
                patch("main.requests.get") as get, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main.main(), 0)
            get.assert_not_called()

    def test_closed_input_exits_cleanly(self):
        with patch("builtins.input", side_effect=EOFError()), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main.main(), 0)


if __name__ == "__main__":
    unittest.main()
