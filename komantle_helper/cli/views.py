"""터미널 표현: 값은 Rich 마크업으로 해석하지 않는다."""

import unicodedata

from prompt_toolkit.utils import get_cwidth
from rich.table import Table
from rich.text import Text

from .. import __version__
from .commands import COMMANDS, HINTS

ACCENT = '#d7875f'
STYLES = {'': '', 'accent': ACCENT, 'title': 'bold', 'muted': 'ansibrightblack',
          'selected': 'reverse', 'error': 'ansired', 'success': 'ansigreen',
          'input': '', 'input-border': 'ansibrightblack', 'input-label': 'bold ' + ACCENT,
          'completion-menu.completion': '',
          'completion-menu.completion.current': 'reverse',
          'completion-menu.meta.completion': 'ansibrightblack',
          'completion-menu.meta.completion.current': 'reverse',
          'scrollbar.background': '', 'scrollbar.button': ACCENT}


def safe(value):
    return ''.join(c if unicodedata.category(c) != 'Cc' or c == '\n' else '�' for c in str(value))


def banner(ascii_only=False):
    face = '( o.o)' if ascii_only else '( •‿•)'
    text = Text()
    text.append(' (\\_/)     ', style=ACCENT)
    text.append('꼬맨틀 헬퍼', style='bold')
    text.append(f'  v{__version__}\n', style='dim')
    text.append(f' {face}    ', style=ACCENT)
    text.append('오늘의 단어로 가는 작은 실마리\n')
    text.append(' / > <\\\n', style=ACCENT)
    text.append('\n 단어를 입력해 추측하거나 / 로 명령을 찾아보세요.\n', style='dim')
    return text


def help_table():
    table = Table(box=None, padding=(0, 2), show_header=False)
    for cmd in COMMANDS:
        table.add_row(Text('/' + cmd.name, style=ACCENT), Text(cmd.description), Text('/' + cmd.alias, style='dim'))
    table.caption = '/hint char 2 · /rank 50 · /round today · /힌트 초성'
    return table


def history_table(game, *, recent=False, page=1):
    rows = list(enumerate(game.guesses, 1))
    rows.sort(key=lambda row: -row[0] if recent else (-row[1].similarity, -row[0]))
    pages = max(1, (len(rows) + 19) // 20)
    if not 1 <= page <= pages:
        from ..core import KomantleError
        raise KomantleError(f'기록 페이지는 1~{pages} 사이예요.')
    table = Table(title=f'{game.number}회 추측 기록 · {page}/{pages}쪽', box=None, padding=(0, 2))
    for label in ('시도', '단어', '유사도', '순위'):
        table.add_column(label, justify='left' if label == '단어' else 'right', overflow='fold')
    for attempt, guess in rows[(page - 1) * 20:page * 20]:
        rank = '정답!' if guess.correct else f'{guess.rank}위' if guess.rank is not None else '순위 미제공'
        style = 'green' if guess.correct else 'bold' if attempt == len(game.guesses) else ''
        table.add_row(str(attempt), Text(safe(guess.word)), f'{guess.similarity:.2f}', rank, style=style)
    if not rows:
        table.caption = '아직 추측한 단어가 없어요. 첫 단어를 입력해보세요.'
    elif page < pages:
        table.caption = f'다음: /history --page {page + 1}' + (' --sort recent' if recent else '')
    return table


def hint_text(data, rank, kind, position=1):
    match kind:
        case 'length': return f'{data.get_length(rank)}글자'
        case 'pos': return data.get_pos(rank)
        case 'initial': return data.get_initial_consonant(rank) or '완성형 한글 초성 없음'
        case 'similarity': return f'{data.get_similarity(rank):.2f}'
        case 'char': return f'{position}번째 · {data.get_one_character(rank, position - 1)}'
        case 'word': return data.get_word(rank)
    raise ValueError(kind)


def target_name(rank):
    return '정답' if rank == 0 else f'{rank}위 단어'


def fit(value, width):
    """한글의 셀 너비를 고려해 선택기 한 줄을 자른다."""
    value = safe(value)
    if get_cwidth(value) <= width:
        return value
    result, used = [], 0
    for char in value:
        size = get_cwidth(char)
        if used + size > max(0, width - 1):
            break
        result.append(char)
        used += size
    return ''.join(result) + '…'
