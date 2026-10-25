"""입력과 응답을 연결하는 실행 기록. 힌트 값은 여기에 저장하지 않는다."""

from contextvars import ContextVar
from dataclasses import dataclass, field

from rich import box
from rich.console import Group
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from .views import ACCENT, fit, safe


@dataclass
class Exchange:
    number: int
    text: str
    messages: list = field(default_factory=list)
    error: bool = False


CURRENT_EXCHANGE = ContextVar('komantle_exchange', default=None)


def request_view(exchange, *, width, plain=False, ascii_only=False, choice=None):
    kind = '확인' if choice is not None else '명령' if exchange.text.startswith('/') else '추측'
    title = f'나 · {kind} #{exchange.number:02d}'
    content = Text(safe(choice if choice is not None else exchange.text), style='bold')
    if plain:
        return Group(Text('\n[' + title + ']'), Padding(content, (0, 2)))
    return Padding(Panel(content, title=Text(title, style='bold'), title_align='left',
                         width=width, box=box.ASCII if ascii_only else box.ROUNDED,
                         border_style=ACCENT, padding=(0, 1)), (1, 0, 0, 0))


def response_view(messages, *, width, exchange=None, phase='응답', error=False,
                  plain=False, ascii_only=False):
    title = f'꼬맨틀 헬퍼 · {phase}' + (f' #{exchange.number:02d}' if exchange else '')
    style = 'red' if error else 'dim'
    content = Group(*messages)
    if plain:
        return Group(Text('[' + title + ']', style=style), Padding(content, (0, 2)), Text(''))
    subtitle = Text(fit(exchange.text, max(1, width - 8)), style='dim') if exchange else None
    return Panel(content, title=Text(title, style='bold red' if error else 'bold'),
                 title_align='left', subtitle=subtitle, subtitle_align='right', width=width,
                 box=box.ASCII if ascii_only else box.ROUNDED,
                 border_style='red' if error else 'bright_black', padding=(0, 1))
