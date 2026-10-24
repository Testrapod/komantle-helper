"""단어 채점과 회차별 게임 기록. Java 분석 없이도 게임을 진행할 수 있다."""

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
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
    if not word or len(word) > 64 or any(c.isspace() or ord(c) < 32 for c in word):
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
    def __init__(self, number, word_manager, *, state_dir=None, scorer=score_upstream):
        self.number, self.scorer = number, scorer
        self.answer = word_manager.get_word(0)
        self.words = {}
        for entry in sorted(word_manager.word_list, key=lambda row: row['word_id']):
            self.words.setdefault(normalize_word(entry['word'].word), entry)
        self.path = Path(state_dir or os.environ.get('KOMANTLE_STATE_DIR', Path.home() / '.local/state/komantle-helper')) / f'game-{number}.json'
        self.guesses, self.given_up, self.storage_warning = [], False, ''
        self._restore()

    @property
    def won(self):
        return any(guess.correct for guess in self.guesses)

    def _restore(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            if data['schema_version'] != 1 or data['round'] != self.number or type(data['given_up']) is not bool or not isinstance(data['guesses'], list) or len(data['guesses']) > 1000:
                raise ValueError()
            guesses, seen = [], set()
            for row in data['guesses']:
                word = normalize_word(row['word'])
                rank, score, correct = row['rank'], row['similarity'], row['correct']
                if word in seen or type(correct) is not bool or (rank is not None and (type(rank) is not int or not 0 <= rank <= 1000)) or type(score) not in (int, float) or not math.isfinite(score) or not -100 <= score <= 100 or correct != (rank == 0) or correct != (word == normalize_word(self.answer)):
                    raise ValueError()
                if any(g.correct for g in guesses):
                    raise ValueError()
                seen.add(word)
                guesses.append(Guess(word, score, rank, correct))
            self.guesses, self.given_up = guesses, data['given_up']
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
                temporary.unlink(missing_ok=True)

    def submit(self, text):
        if self.won or self.given_up:
            raise GameError('이미 끝난 게임입니다. 다른 회차를 선택해주세요.')
        word = normalize_word(text)
        if any(guess.word == word for guess in self.guesses):
            raise GameError('이미 입력한 단어예요. 추측 횟수는 늘어나지 않습니다.')
        if len(self.guesses) >= 1000:
            raise GameError('회차당 최대 1,000번까지 추측할 수 있습니다.')
        row = self.words.get(word)
        guess = Guess(word, row['similarity'], row['word_id'], row['word_id'] == 0) if row else self.scorer(self.number, word)
        if guess.correct != (word == normalize_word(self.answer)):
            raise GameError('채점 결과와 회차 데이터가 일치하지 않습니다. 다시 불러와주세요.')
        self.guesses.append(guess)
        self._save()
        return guess

    def give_up(self):
        if not self.won:
            self.given_up = True
            self._save()
        return self.answer


def run_game(number, word_manager, *, state_dir=None):
    game = GameSession(number, word_manager, state_dir=state_dir)
    print(f'\n{number}회 꼬맨틀 게임 · /기록 /포기 /돌아가기')
    if game.storage_warning:
        print(game.storage_warning)
    if game.won:
        print(f'이미 {len(game.guesses)}번 만에 맞힌 회차입니다.')
        return
    if game.given_up:
        print(f'포기한 회차입니다. 정답: {game.answer}')
        return
    print(f'이어서 {len(game.guesses) + 1}번째 추측을 입력하세요.')
    while True:
        text = input('추측 > ').strip()
        command = text.lower()
        if command in ('/돌아가기', '/back', '/q', '/quit'):
            return
        if command in ('/기록', '/history'):
            for attempt, guess in sorted(enumerate(game.guesses, 1), key=lambda item: -item[1].similarity):
                print(f'{attempt}번째 · {guess.word} · {guess.similarity:.2f} · {str(guess.rank) + "위" if guess.rank is not None else "순위 미제공"}')
            continue
        if command in ('/포기', '/giveup'):
            if input('정답을 공개하고 포기할까요? [y/N] > ').strip().lower() == 'y':
                print(f'정답: {game.give_up()}')
                return
            continue
        if text.startswith('/'):
            print('사용 가능한 명령: /기록 /포기 /돌아가기')
            continue
        try:
            guess = game.submit(text)
            rank = '정답!' if guess.correct else f'{guess.rank}위' if guess.rank is not None else '순위 미제공'
            print(f'{len(game.guesses)}번째 · {guess.word} · 유사도 {guess.similarity:.2f} · {rank}')
            if game.storage_warning:
                print(game.storage_warning)
            if game.won:
                print(f'축하합니다! {len(game.guesses)}번 만에 정답을 맞혔어요.')
                return
        except GameError as error:
            print(error)
