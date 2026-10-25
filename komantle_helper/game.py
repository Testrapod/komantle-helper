"""단어 채점과 회차별 게임 기록. Java 분석 없이도 게임을 진행할 수 있다."""

from dataclasses import asdict, dataclass
import json
import math
import os
import re
from pathlib import Path
import tempfile
import unicodedata
from urllib.parse import quote

import requests

GUESS_URL = "https://semantle-ko.newsjel.ly/guess"


class GameError(ValueError):
    pass


def normalize_word(value):
    if not isinstance(value, str):
        raise GameError("단어를 입력해주세요.")
    word = unicodedata.normalize('NFC', value.strip()).lower()
    if not word or len(word) > 64 or any(c.isspace() or unicodedata.category(c) == 'Cc' for c in word):
        raise GameError("공백 없이 1~64글자의 단어를 입력해주세요.")
    return word


@dataclass(frozen=True)
class Guess:
    word: str
    similarity: float
    rank: int | None
    correct: bool


def score_upstream(number, text, *, request_get=None):
    if type(number) is not int or number < 0:
        raise GameError("회차가 올바르지 않습니다.")
    word = normalize_word(text)
    try:
        response = (request_get or requests.get)(f'{GUESS_URL}/{number}/{quote(word, safe="")}', timeout=15)
        if response.status_code == 404:
            raise GameError("원본 사전에 없는 단어예요. 다른 단어를 입력해주세요.")
        if response.status_code == 422:
            raise GameError("이 회차의 실시간 채점 기간이 지났어요. 보관된 단어의 점수는 계속 확인할 수 있어요.")
        if response.status_code == 429:
            raise GameError("채점 요청이 많아요. 잠시 후 다시 시도해주세요.")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('guess') != word:
            raise ValueError()
        score = data.get('sim')
        if type(score) not in (float, int) or not math.isfinite(score) or not -1 <= score <= 1:
            raise ValueError()
        raw_rank = data.get('rank')
        if raw_rank == '정답!':
            rank = 0
        elif type(raw_rank) is int and 1 <= raw_rank <= 1000:
            rank = raw_rank
        elif raw_rank == '1000위 이상':
            rank = None
        else:
            raise ValueError()
        if rank == 0 and score != 1:
            raise ValueError()
        return Guess(word, score * 100, rank, rank == 0)
    except requests.RequestException as error:
        raise GameError("채점 서버에 연결하지 못했어요. 잠시 후 다시 시도해주세요.") from error
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, GameError):
            raise
        raise GameError("채점 서버의 응답 형식이 올바르지 않습니다.") from error


class GameSession:
    def __init__(self, data, *, state_dir=None, scorer=score_upstream):
        self.number, self.scorer = data.number, scorer
        self.answer = data.get_word(0)
        self.words = index_words(data)
        self.path = state_directory(state_dir) / f'game-{self.number}.json'
        self.guesses, self.given_up, self.storage_warning = [], False, ''
        self._restore()

    def rebind(self, data):
        """갱신된 단어 데이터에 연결하되 저장 실패한 메모리 기록도 보존한다."""
        if data.number != self.number:
            raise GameError('다른 회차 데이터에는 기록을 연결할 수 없습니다.')
        answer, words = data.get_word(0), index_words(data)
        guesses = []
        for guess in self.guesses:
            cached = words.get(guess.word)
            updated = Guess(guess.word, cached['similarity'], cached['word_id'], cached['word_id'] == 0) if cached else guess
            if updated.correct != (guess.word == normalize_word(answer)):
                raise GameError('회차 정답 데이터가 변경됐어요. 기록을 확인한 후 다시 시작해주세요.')
            guesses.append(updated)
        changed = guesses != self.guesses
        self.answer, self.words, self.guesses = answer, words, guesses
        if changed:
            self._save()

    @property
    def won(self):
        return any(guess.correct for guess in self.guesses)

    def _restore(self):
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text())
            if data['schema_version'] != 1 or data['round'] != self.number or type(data['given_up']) is not bool or not isinstance(data['guesses'], list) or len(data['guesses']) > 1000:
                raise ValueError()
            guesses, seen, corrected = [], set(), False
            for row in data['guesses']:
                word = normalize_word(row['word'])
                rank, score, correct = row['rank'], row['similarity'], row['correct']
                if word in seen or type(correct) is not bool or (rank is not None and (type(rank) is not int or not 0 <= rank <= 1000)) or type(score) not in (int, float) or not math.isfinite(score) or not -100 <= score <= 100 or correct != (rank == 0) or correct != (word == normalize_word(self.answer)):
                    raise ValueError()
                if any(g.correct for g in guesses):
                    raise ValueError()
                cached = self.words.get(word)
                if cached:
                    corrected |= score != cached['similarity'] or rank != cached['word_id']
                    rank, score = cached['word_id'], cached['similarity']
                seen.add(word)
                guesses.append(Guess(word, score, rank, correct))
            self.guesses, self.given_up = guesses, data['given_up']
            if corrected:
                self._save()
        except (OSError, ValueError, KeyError, TypeError):
            self.storage_warning = '기존 게임 기록을 읽지 못해 새 게임으로 시작합니다.'

    def _save(self):
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {'schema_version': 1, 'round': self.number, 'given_up': self.given_up,
                    'guesses': [asdict(guess) for guess in self.guesses]}
            with tempfile.NamedTemporaryFile(dir=self.path.parent, mode='w', encoding='utf-8', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            os.replace(temporary, self.path)
            self.storage_warning = ''
        except OSError:
            self.storage_warning = '기록을 파일에 저장하지 못했습니다. 이번 실행에서는 계속 플레이할 수 있어요.'
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @property
    def finished(self):
        return self.won or self.given_up

    def prepare(self, text):
        """채점은 파일을 변경하지 않는다. 취소된 작업은 결과를 버릴 수 있다."""
        if self.won or self.given_up:
            raise GameError('이미 끝난 게임입니다. 다른 회차를 선택해주세요.')
        word = normalize_word(text)
        if any(guess.word == word for guess in self.guesses):
            raise GameError('이미 입력한 단어예요. 추측 횟수는 늘어나지 않습니다.')
        if len(self.guesses) >= 1000:
            raise GameError('회차당 최대 1,000번까지 추측할 수 있습니다.')
        row = self.words.get(word)
        guess = Guess(word, row['similarity'], row['word_id'], row['word_id'] == 0) if row else self.scorer(self.number, word)
        valid_rank = guess.rank is None or (type(guess.rank) is int and 0 <= guess.rank <= 1000)
        valid_score = type(guess.similarity) in (int, float) and math.isfinite(guess.similarity) and -100 <= guess.similarity <= 100
        if (guess.word != word or type(guess.correct) is not bool or not valid_score or not valid_rank
                or guess.correct != (guess.rank == 0) or (guess.correct and guess.similarity != 100)
                or guess.correct != (word == normalize_word(self.answer))):
            raise GameError('채점 결과와 회차 데이터가 일치하지 않습니다. 다시 불러와주세요.')
        return guess

    def commit(self, guess):
        if self.finished or any(row.word == guess.word for row in self.guesses):
            raise GameError('게임 상태가 바뀌었어요. 다시 입력해주세요.')
        self.guesses.append(guess)
        self._save()
        return guess

    def submit(self, text):
        return self.commit(self.prepare(text))

    def give_up(self):
        if not self.won:
            self.given_up = True
            self._save()
        return self.answer


def index_words(data):
    words = {}
    for entry in sorted(data.word_list, key=lambda row: row['word_id']):
        words.setdefault(normalize_word(entry['word'].word), entry)
    return words


def state_directory(directory=None):
    return Path(directory or os.environ.get('KOMANTLE_STATE_DIR', Path.home() / '.local/state/komantle-helper'))


def record_files(directory=None, number=None):
    root = state_directory(directory)
    if number is not None:
        target = root / f'game-{number}.json'
        return [target] if target.exists() else []
    return sorted(p for p in root.glob('game-*.json') if re.fullmatch(r'game-\d+\.json', p.name) and (p.is_file() or p.is_symlink()))


def delete_records(directory=None, number=None):
    files = record_files(directory, number)
    removed, failed = [], []
    for target in files:
        try:
            target.unlink(missing_ok=True)
            removed.append(target.name)
        except OSError:
            failed.append(target.name)
    if failed:
        raise GameError(f'{len(removed)}개 삭제, {len(failed)}개 삭제 실패: ' + ', '.join(failed))
    return len(removed)
