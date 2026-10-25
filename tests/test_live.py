"""실제 API/Java 검증. KOMANTLE_LIVE_TEST=1로 명시적으로 실행한다."""

from datetime import datetime
import os
import unittest

from komantle_helper import core
from komantle_helper.data import fetch_round


@unittest.skipUnless(os.environ.get("KOMANTLE_LIVE_TEST") == "1", "실제 API 테스트는 별도로 실행")
class LiveTests(unittest.TestCase):
    def test_today_all_hints_and_yesterday(self):
        number = (datetime.now(core.SEOUL_TIME_ZONE) - core.KOMANTLE_START_DATE).days
        today = fetch_round(number)
        self.assertEqual({row["word_id"] for row in today.word_list}, set(range(1001)))
        for rank in range(1001):
            with self.subTest(rank=rank):
                word = today.get_word(rank)
                self.assertEqual(today.get_length(rank), len(word))
                self.assertEqual(today.get_one_character(rank, 0), word[0])
                self.assertIsInstance(today.get_initial_consonant(rank), str)
                self.assertTrue(-100 <= today.get_similarity(rank) <= 100)
                self.assertIn(today.get_pos(rank), ("명사", "동사", "형용사", "부사", "기타"))
        yesterday = fetch_round(number - 1)
        self.assertEqual(len(yesterday.word_list), 1001)
        self.assertEqual(len(today.word_list), 1001)
        self.assertIsNot(today.word_list, yesterday.word_list)


if __name__ == "__main__":
    unittest.main()
