"""파싱·도움말·완성을 공유하는 단일 명령 명세."""

from dataclasses import dataclass
import difflib
import shlex

from prompt_toolkit.completion import Completer, Completion

from ..core import KomantleError

HINTS = {'length': '길이', 'pos': '품사', 'initial': '초성', 'similarity': '유사도', 'char': '한 글자', 'word': '전체 단어'}
HINT_ALIASES = {'길이': 'length', '품사': 'pos', '초성': 'initial', '유사도': 'similarity', '글자': 'char', '단어': 'word'}


@dataclass(frozen=True)
class Command:
    name: str
    alias: str
    description: str
    usage: str = ''


COMMANDS = (
    Command('help', '도움말', '명령과 사용 예시'),
    Command('round', '회차', '플레이할 회차 선택', '[today|latest|번호]'),
    Command('rank', '순위', '힌트를 볼 순위 선택', '[0~1000]'),
    Command('hint', '힌트', '필요한 만큼 힌트 공개', '[length|pos|initial|similarity|char 위치|word]'),
    Command('hide', '숨기기', '공개한 힌트 숨기기', '[all|힌트 종류]'),
    Command('history', '기록', '유사도 순 추측 기록', '[--sort similarity|recent] [--page 번호]'),
    Command('giveup', '포기', '정답을 공개하고 이번 회차 마치기'),
    Command('records', '기록삭제', '현재 또는 전체 회차 기록 삭제', 'delete [current|all]'),
    Command('status', '상태', '데이터 출처와 기록 저장 상태'),
    Command('links', '링크', '원본 게임과 GitHub'),
    Command('refresh', '새로고침', '데이터 목록과 현재 회차 갱신'),
    Command('settings', '설정', '색상과 로딩 효과 설정', '[color|animation on|off]'),
    Command('clear', '화면정리', '화면 정리 · 게임 기록 유지'),
    Command('quit', '종료', 'CLI 종료'),
)
BY_NAME = {key: cmd for cmd in COMMANDS for key in (cmd.name, cmd.alias)}


def parse(text):
    try:
        parts = shlex.split(text[1:])
    except ValueError as error:
        raise KomantleError('따옴표가 닫히지 않았어요. 명령을 확인해주세요.') from error
    if not parts:
        return 'help', []
    key = parts[0].lower()
    if key not in BY_NAME:
        closest = difflib.get_close_matches(key, BY_NAME, n=1, cutoff=.45)
        tip = f' /{BY_NAME[closest[0]].name} 을 찾으셨나요?' if closest else ' /help 로 명령을 확인해주세요.'
        raise KomantleError('알 수 없는 명령이에요.' + tip)
    args = parts[1:]
    if key == '기록삭제' and (not args or args[0] != 'delete'):
        args.insert(0, 'delete')
    return BY_NAME[key].name, args


def hint_kind(value):
    result = HINT_ALIASES.get(value, value)
    if result not in HINTS:
        raise KomantleError('힌트 종류를 확인해주세요. /hint 로 선택할 수 있어요.')
    return result


def integer(value, minimum, maximum, label):
    if not value.isascii() or not value.isdecimal() or not minimum <= int(value) <= maximum:
        raise KomantleError(f'{label}는 {minimum}~{maximum} 사이의 정수로 입력해주세요.')
    return int(value)


class CommandCompleter(Completer):
    def __init__(self, rounds=lambda: []):
        self.rounds = rounds

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith('/') or '\n' in text:
            return
        tokens = text[1:].split()
        if ' ' not in text:
            prefix = text[1:].lower()
            for cmd in COMMANDS:
                if prefix in cmd.name or prefix in cmd.alias:
                    yield Completion('/' + cmd.name, start_position=-len(text), display='/' + cmd.name,
                                     display_meta=cmd.description)
            return
        key = tokens[0] if tokens else ''
        cmd = BY_NAME.get(key)
        if not cmd:
            return
        args = tokens[1:]
        prefix = '' if text.endswith(' ') else (args[-1] if args else '')
        finished = args if text.endswith(' ') else args[:-1]
        candidates = []
        if cmd.name in ('hint', 'hide') and not finished:
            candidates = list(HINTS.items()) + ([('all', '모두 숨기기')] if cmd.name == 'hide' else [])
        elif cmd.name == 'round' and not finished:
            candidates = [('today', '오늘 회차'), ('latest', '최신 보관 회차')] + [(str(row['round']), row['date']) for row in reversed(self.rounds())]
        elif cmd.name == 'records':
            candidates = [('delete', '기록 삭제')] if not finished else [('current', '현재 회차'), ('all', '전체 회차')] if finished == ['delete'] else []
        elif cmd.name == 'settings':
            candidates = [('color', '색상'), ('animation', '로딩 효과')] if not finished else [('on', '사용'), ('off', '끄기')] if len(finished) == 1 else []
        elif cmd.name == 'history':
            candidates = [('similarity', '유사도 순'), ('recent', '최근 순')] if finished and finished[-1] == '--sort' else [('--sort', '정렬 기준'), ('--page', '페이지 번호')]
        elif cmd.name == 'rank' and not finished:
            candidates = [('0', '정답의 힌트'), ('1', '1위 단어의 힌트'), ('1000', '1000위 단어의 힌트')]
        for value, description in candidates:
            if prefix in value or prefix in description:
                yield Completion(value, start_position=-len(prefix), display_meta=description)
