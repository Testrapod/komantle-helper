from datetime import datetime
from functools import cached_property, lru_cache
import requests
from zoneinfo import ZoneInfo

from konlpy.tag import Okt


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


class KomantleError(ValueError):
    """사용자에게 표시할 수 있는 조회/분석 오류."""


@lru_cache(maxsize=1)
def get_tokenizer():
    try:
        return Okt()
    except (RuntimeError, OSError, ValueError) as error:
        raise KomantleError(
            "품사 분석기를 시작하지 못했습니다. Java 설치와 JAVA_HOME을 확인해주세요."
        ) from error


class Word:
    word: str               # 단어
    pos: str                # 품사 (명사, 동사, 형용사, 부사, 기타)
    initial_consonant: str  # 초성
    length: int             # 단어 길이


    def __init__(self, word: str):
        self.word = word
        self.initial_consonant = self._get_initial_consonant()
        self.length = self._get_length()


    @cached_property
    def pos(self) -> str:
        # 품사가 필요한 단어만 분석하고 결과를 재사용한다.
        return self._get_pos()


    def __repr__(self):
        return f"Word(word: {self.word}, pos: {self.pos}, initial_consonant: {self.initial_consonant}, length: {self.length})"


    def _get_pos(self) -> str:
        # 여러 형태소로 분리되는 단어는 기존 규칙대로 '기타'로 분류한다.
        tokenizer = get_tokenizer()
        pos_tags = tokenizer.pos(self.word)
        # print(pos_tags)
        
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


class WordManager:
    """
    [
        {
            "word_id": int,       # 단어 순위 (0: 정답)
            "word": Word,         # 단어
            "similarity": float,  # 유사도
        }
    ]
    """
    def __init__(self, komantle_no: int):
        if isinstance(komantle_no, bool) or not isinstance(komantle_no, int) or komantle_no < 0:
            raise KomantleError("꼬맨틀 회차는 0 이상의 정수여야 합니다.")
        url = f"{KOMANTLE_URL}/{komantle_no}"

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                raise KomantleError(f"{komantle_no}번째 꼬맨틀 정보를 찾을 수 없습니다.")
            if response.status_code == 422:
                message = f"{komantle_no}번째 꼬맨틀 정보를 조회할 수 없습니다."
                try:
                    payload = response.json()
                    detail = payload.get("detail") if isinstance(payload, dict) else None
                    if isinstance(detail, dict) and isinstance(detail.get("description"), str):
                        message += f" {detail['description']}"
                except ValueError:
                    pass
                raise KomantleError(message)
            response.raise_for_status()
        except requests.RequestException as error:
            raise KomantleError("꼬맨틀 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.") from error

        try:
            data = response.json()
            answer = data["key"]
            scores = data["top_scores"]
            if not isinstance(answer, str) or not answer or not isinstance(scores, list):
                raise ValueError("Invalid answer or scores")

            self.word_list = [{"word_id": 0, "word": Word(answer), "similarity": 100.0}]
            seen_ranks = {0}
            for rank, text, score in scores:
                if type(rank) is not int or not 1 <= rank <= 1000 or rank in seen_ranks:
                    raise ValueError("Invalid or duplicate rank")
                if not isinstance(text, str) or not text:
                    raise ValueError("Invalid word")
                similarity = float(score)
                if not -100 <= similarity <= 100:
                    raise ValueError("Invalid similarity")
                seen_ranks.add(rank)
                self.word_list.append({"word_id": rank, "word": Word(text), "similarity": similarity})
        except (ValueError, KeyError, TypeError) as error:
            raise KomantleError("꼬맨틀 서버의 응답 형식이 올바르지 않습니다.") from error

        self._words_by_rank = {entry["word_id"]: entry for entry in self.word_list}


    def get_word(self, word_id: int) -> str:
        return self._find_word(word_id)["word"].word


    def get_pos(self, word_id: int) -> str:
        return self._find_word(word_id)["word"].pos
    

    def get_initial_consonant(self, word_id: int) ->  str:
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


def _run():
    # TODO: 메인 로직 복잡도 이슈
    # - print 문 너무 많이 사용됨 -> 공통화 필요
    # - while 및 if 문 너무 많이 사용됨 -> 간소화 필요
    print("      +----------------------------+")
    print("      | Hello I'm Komantle Helper! |")
    print("      +----------------------------+")
    print(r"(\_/)  ")
    print("( •‿•) ")
    print(r"/ > <\ ")

    komantle_no = (datetime.now(tz=SEOUL_TIME_ZONE) - KOMANTLE_START_DATE).days

    # 꼬맨틀 회차 선택
    while True:
        print("")
        print(f"오늘은 {komantle_no}번째 꼬맨틀 입니다. 그대로 진행하시겠습니까?")
        print("1. 예")
        print("2. 아니오")
        print("Q. 종료")
        command = input("> ").strip().upper()

        if command == "Q":
            print("프로그램을 종료합니다. 다음에 또 만나요~ (_ _)")
            return
        elif command == "1":
            break
        elif command == "2":
            print("")
            print("진행하고 싶은 꼬맨틀 회차를 입력해주세요.")
            command = input("> ").strip().upper()

            if command.isdigit():
                komantle_no = int(command)
                break
            else:
                print("잘못된 입력 입니다. 숫자로 입력해 주세요.")
                continue
        else:
            print("잘못된 명령어 입니다. 다시 입력해주세요.")
            
    word_manager = WordManager(komantle_no)

    command_map = {
        "1": {"name": "품사", "func": word_manager.get_pos},
        "2": {"name": "초성", "func": word_manager.get_initial_consonant},
        "3": {"name": "단어 길이", "func": word_manager.get_length},
        "4": {"name": "유사도", "func": word_manager.get_similarity},
        "5": {"name": "단어", "func": word_manager.get_word},
    }

    # 꼬맨틀 헬퍼
    while True:
        print("")
        print("원하시는 명령어를 입력해 주세요.")
        for key, value in command_map.items():
            print(f"{key}. {value['name']} 확인")
        print("Q. 종료")
        command = input("> ").strip().upper()

        if command == "Q":
            print("프로그램을 종료합니다. 도움이 되셨길 바랍니다~ (_ _)")
            break
        elif command in ["1", "2", "3", "4", "5"]:
            while True:
                print("")
                print("확인하고자 하는 단어의 순위를 0 ~ 1000 사이 값으로 입력해 주세요. (0: 정답, B: 돌아가기)")
                target_command = input("> ").strip().upper()

                if target_command == "B":
                    print("처음 화면으로 돌아갑니다.")
                    break

                if target_command.isdigit():
                    word_id = int(target_command)
                    if 0 <= word_id <= 1000:
                        target_name = "정답" if word_id == 0 else f"{word_id}위"
                        func_name = command_map[command]["name"]
                        try:
                            func_value = command_map[command]["func"](word_id)
                        except KomantleError as error:
                            print(error)
                            break

                        print(f"{target_name} 단어의 {func_name}는(은) '{func_value}' 입니다.")
                        break
                    else:
                        print("잘못된 랭킹입니다. 0 ~ 1000 사이 값으로 입력해주세요.")
                        continue
                else:
                    print("잘못된 입력 입니다. 0 ~ 1000 혹은 B 를 입력해 주세요.")
                    continue
        else:
            print("잘못된 명령어 입니다. 다시 입력해주세요.")


def main():
    try:
        _run()
    except KomantleError as error:
        print(error)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\n프로그램을 종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
