from datetime import datetime, timedelta
from functools import cached_property, lru_cache
from zoneinfo import ZoneInfo


SEOUL_TIME_ZONE = ZoneInfo("Asia/Seoul")

KOMANTLE_URL = "https://semantle-ko.newsjel.ly/top_scores"
KOMANTLE_START_DATE = datetime(2022, 4, 1, tzinfo=SEOUL_TIME_ZONE)
REQUEST_TIMEOUT = 15

START_UNICODE = 0xAC00  # "가"
END_UNICODE = 0xD7A3    # "힣"

INITIAL_CONSONANTS = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
]


def get_today_round(now=None):
    now = now or datetime.now(SEOUL_TIME_ZONE)
    if now.tzinfo is None:
        raise ValueError("시간대가 포함된 시각이 필요합니다.")
    return (now.astimezone(SEOUL_TIME_ZONE).date() - KOMANTLE_START_DATE.date()).days


def get_round_date(number):
    if type(number) is not int or number < 0:
        raise ValueError("회차는 0 이상의 정수여야 합니다.")
    return KOMANTLE_START_DATE.date() + timedelta(days=number)


class KomantleError(ValueError):
    """사용자에게 표시할 수 있는 조회/분석 오류."""


@lru_cache(maxsize=1)
def get_tokenizer():
    try:
        from konlpy.tag import Okt
        return Okt()
    except (ImportError, RuntimeError, OSError, ValueError) as error:
        raise KomantleError(
            "품사 분석기를 시작하지 못했습니다. Java와 JAVA_HOME을 확인해주세요. 분석 모듈은 pip install -e '.[analysis]' 로 설치할 수 있어요."
        ) from error


class Word:
    """저장된 품사를 사용하고, 없을 때만 분석하는 단어."""

    def __init__(self, word: str, *, pos: str | None = None):
        if not isinstance(word, str) or not word or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in word):
            raise KomantleError("단어 데이터 형식이 올바르지 않습니다.")
        if pos is not None:
            self.pos = pos
        self.word = word
        self.initial_consonant = self._get_initial_consonant()
        self.length = self._get_length()

    @cached_property
    def pos(self) -> str:
        # 품사가 필요한 단어만 분석하고 결과를 재사용한다.
        return self._get_pos()

    def __repr__(self):
        return f"Word({self.word!r})"

    def _get_pos(self) -> str:
        # 여러 형태소로 분리되는 단어는 기존 규칙대로 '기타'로 분류한다.
        tokenizer = get_tokenizer()
        pos_tags = tokenizer.pos(self.word)

        pos_mapping = {
            "Noun": "명사",
            "Verb": "동사",
            "Adjective": "형용사",
            "Adverb": "부사",
        }

        for token, pos in pos_tags:
            if token == self.word:
                return pos_mapping.get(pos, "기타")
        return "기타"

    def _get_initial_consonant(self) -> str:
        result = []

        for char in self.word:
            if START_UNICODE <= ord(char) <= END_UNICODE:
                syllable_index = ord(char) - START_UNICODE
                initial_index = syllable_index // (21 * 28)   # 중성(가운데소리): 21개 * 종성(끝소리): 28개

                result.append(INITIAL_CONSONANTS[initial_index])
            else:
                continue

        return "".join(result)

    def _get_length(self) -> int:
        return len(self.word)


class RoundData:
    """힌트와 게임이 공유하는 회차 데이터. 네트워크나 화면에 의존하지 않는다."""

    def __init__(self, number, words, *, source="원본 API", collected_at=None):
        self.number = number
        self.word_list = words
        self.source = source
        self.collected_at = collected_at
        self._words_by_rank = {entry["word_id"]: entry for entry in words}

    def get_word(self, word_id: int) -> str:
        return self._find_word(word_id)["word"].word

    def get_pos(self, word_id: int) -> str:
        return self._find_word(word_id)["word"].pos

    def get_initial_consonant(self, word_id: int) -> str:
        return self._find_word(word_id)["word"].initial_consonant

    def get_length(self, word_id: int) -> int:
        return self._find_word(word_id)["word"].length

    def get_similarity(self, word_id: int) -> float:
        return self._find_word(word_id)["similarity"]

    def get_one_character(self, word_id: int, index: int) -> str:
        word = self.get_word(word_id)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(word):
            raise KomantleError(f"글자 위치는 0 ~ {len(word) - 1} 사이여야 합니다.")
        return word[index]

    def _find_word(self, word_id: int) -> dict:
        if isinstance(word_id, bool) or not isinstance(word_id, int) or word_id not in self._words_by_rank:
            raise KomantleError(f"{word_id}위 단어 정보를 찾을 수 없습니다. 0 ~ 1000 사이 순위를 확인해주세요.")
        return self._words_by_rank[word_id]

