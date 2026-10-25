"""하나의 입력창에서 추측·힌트·기록을 사용하는 인라인 터미널 앱."""

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from prompt_toolkit.application import Application, run_in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, VSplit, Layout, Window, ConditionalContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import DynamicStyle, Style
from prompt_toolkit.utils import get_cwidth
from rich.console import Console
from rich.text import Text

from .. import __version__
from ..archive import atomic_write, json_bytes
from ..core import KomantleError, get_round_date, get_today_round
from ..data import Repository
from ..game import GameError, GameSession, delete_records, record_files, state_directory
from .commands import HINTS, CommandCompleter, hint_kind, integer, parse
from .workers import run_io
from .transcript import CURRENT_EXCHANGE, Exchange, request_view, response_view
from .views import STYLES, banner, help_table, history_table, hint_text, safe, target_name, fit


@dataclass
class Picker:
    title: str
    # value, label, description. Values are commands, never archived hidden words.
    items: list
    confirm: bool = False
    selected: int = 0
    action: object = None
    exchange: Exchange | None = None


class TerminalApp:
    def __init__(self, repository, *, state_dir=None, plain=False, no_color=False,
                 no_animation=False, ascii_only=False, console=None, input=None, output=None):
        self.repository = repository
        self.state_dir = state_directory(state_dir)
        self.plain = plain
        self.ascii_only = ascii_only
        self.forced_no_color = no_color or 'NO_COLOR' in os.environ
        self.forced_no_animation = no_animation
        self.preferences = {'color': True, 'animation': True}
        self.config_warning = ''
        try:
            config = json.loads((self.state_dir / 'settings.json').read_text())
            if not isinstance(config, dict) or any(type(config.get(k, True)) is not bool for k in self.preferences):
                raise ValueError()
            self.preferences.update({k: config[k] for k in self.preferences if k in config})
        except FileNotFoundError:
            pass
        except (ValueError, OSError):
            self.config_warning = '화면 설정을 읽지 못해 기본값을 사용해요.'
        self.console = console or Console(no_color=self.no_color, force_terminal=False if plain else None,
                                          highlight=False, markup=False)
        self.console.no_color = self.no_color
        self.data = self.game = None
        self.sessions = {}
        self.rank = 0
        self.revealed = {}
        self.picker = None
        self.busy = ''
        self.notice = ''
        self.work = None
        self.work_exchange = None
        self.exchange_number = 0
        self.closed = False
        self.application = None
        self.start_day = get_today_round()
        self.completer = CommandCompleter(lambda: self.repository.rounds)
        if not plain:
            self._build(input, output)

    @property
    def no_color(self):
        return self.forced_no_color or not self.preferences['color']

    def invalidate(self):
        if self.application:
            self.application.invalidate()

    def transcript_width(self):
        columns = self.application.output.get_size().columns if self.application else self.console.width
        return max(12, min(100, columns))

    async def write(self, value):
        if self.application and self.application.is_running:
            await run_in_terminal(lambda: self.console.print(value))
        else:
            self.console.print(value)

    async def emit(self, value, *, error=False):
        if isinstance(value, str):
            value = Text(safe(value), style='red' if error else '')
        exchange = CURRENT_EXCHANGE.get()
        if exchange:
            exchange.messages.append(value)
            exchange.error |= error
        else:
            await self.write(response_view([value], width=self.transcript_width(), phase='안내',
                                           error=error, plain=self.plain, ascii_only=self.ascii_only))

    async def flush_exchange(self, exchange):
        if not exchange.messages:
            return
        messages, exchange.messages = exchange.messages, []
        error, exchange.error = exchange.error, False
        pending = self.picker and self.picker.exchange is exchange
        phase = '오류' if error else '확인 대기' if pending and self.picker.confirm else '선택 대기' if pending else '응답'
        await self.write(response_view(messages, exchange=exchange, width=self.transcript_width(),
                                       phase=phase, error=error, plain=self.plain,
                                       ascii_only=self.ascii_only))

    def _style(self):
        return Style.from_dict({k: ('bold' if k == 'title' else '') for k in STYLES} if self.no_color else STYLES)

    def _build(self, input, output):
        self.buffer = Buffer(history=InMemoryHistory(), completer=self.completer,
                             complete_while_typing=Condition(lambda: not self.picker and self.buffer.text.startswith('/')),
                             multiline=False, on_text_changed=lambda _: self._text_changed())
        keys = KeyBindings()

        @keys.add('enter')
        def enter(event):
            if self.picker:
                self._choose()
                return
            completion = self.buffer.complete_state
            if completion and completion.current_completion:
                self.buffer.apply_completion(completion.current_completion)
                return
            text = self.buffer.text.strip()
            if not text:
                return
            if '\n' in text or '\r' in text:
                self.notice = '한 번에 단어 또는 명령 하나를 입력해주세요.'
                return
            if self.busy and not text.startswith('/'):
                self.notice = '채점 중이에요. Ctrl+C 로 취소할 수 있어요.'
                return
            self.buffer.append_to_history()
            self.buffer.reset()
            self.application.create_background_task(self.execute(text))

        @keys.add('tab')
        def tab(event):
            if self.picker:
                self._move(1)
            elif self.buffer.complete_state:
                self.buffer.complete_next()
            else:
                self.buffer.start_completion(select_first=True)

        @keys.add('down')
        def down(event):
            if self.picker: self._move(1)
            elif self.buffer.complete_state: self.buffer.complete_next()
            else: self.buffer.history_forward()

        @keys.add('up')
        def up(event):
            if self.picker: self._move(-1)
            elif self.buffer.complete_state: self.buffer.complete_previous()
            else: self.buffer.history_backward()

        @keys.add('escape')
        def escape(event):
            if self.picker:
                self.cancel_picker()
            else:
                self.buffer.cancel_completion()

        @keys.add('c-c')
        def cancel(event):
            self.cancel_work()
            self.cancel_picker()
            self.buffer.reset()
            self.notice = '취소했어요. 계속 입력할 수 있어요.'

        @keys.add('c-d')
        def eof(event):
            if self.buffer.text:
                self.buffer.delete()
            else:
                self.close()

        @keys.add('<bracketed-paste>')
        def paste(event):
            text = event.data.replace('\r\n', '\n').replace('\r', '\n')
            if '\n' in text:
                self.notice = '여러 줄은 자동 제출하지 않아요. 단어 또는 명령 하나로 수정해주세요.'
            self.buffer.insert_text(text)

        prompt = Window(FormattedTextControl(lambda: [('class:accent', ' > ' if self.ascii_only else ' › ')]), width=3, height=1)
        edge = '|' if self.ascii_only else '│'
        input_row = VSplit([Window(char=edge, width=1, style='class:input-border'), prompt,
                            Window(BufferControl(buffer=self.buffer), height=1), Window(width=1),
                            Window(char=edge, width=1, style='class:input-border')], height=1)
        input_box = HSplit([Window(FormattedTextControl(self._input_top), height=1), input_row,
                            Window(FormattedTextControl(self._input_bottom), height=1)], height=3)
        root = HSplit([
            ConditionalContainer(Window(FormattedTextControl(self._hints), height=Dimension(min=1, max=9), wrap_lines=True, dont_extend_height=True),
                                 filter=Condition(lambda: self.data is not None and not self.picker)),
            input_box,
            CompletionsMenu(max_height=7, scroll_offset=1),
            ConditionalContainer(Window(FormattedTextControl(self._choices), height=Dimension(min=2, max=9), wrap_lines=True, dont_extend_height=True),
                                 filter=Condition(lambda: self.picker is not None)),
            Window(FormattedTextControl(self._status), height=Dimension(min=1, max=3), wrap_lines=True, dont_extend_height=True),
            Window(FormattedTextControl(self._key_help), height=1),
        ])
        self.application = Application(layout=Layout(root, focused_element=self.buffer), key_bindings=keys,
                                       style=DynamicStyle(self._style), full_screen=False,
                                       input=input, output=output,
                                       erase_when_done=True)

    def _text_changed(self):
        if self.picker and not self.picker.confirm:
            self.picker.selected = 0
        self.invalidate()

    def _hints(self):
        if not self.data:
            return []
        header = [('class:accent', f' 힌트 · {self.data.number}회 · {target_name(self.rank)}\n')]
        cells = []
        for kind, label in HINTS.items():
            value = safe(self.revealed.get(kind, '숨김'))
            cells.append(f'{label}  {value}')
        columns = self.application.output.get_size().columns
        if columns < 60 or self.application.output.get_size().rows < 15:
            opened = [f'{HINTS[kind]}  {safe(value)}' for kind, value in reversed(list(self.revealed.items()))]
            content = '\n'.join(' ' + cell for cell in opened) if opened else ' /hint 로 작은 힌트부터 열어보세요.'
        else:
            content = '\n'.join(' ' + '    '.join(cells[i:i + 2]) for i in range(0, len(cells), 2))
        return header + [('', content)]

    def _input_top(self):
        width = self.application.output.get_size().columns
        label = '확인 선택' if self.picker and self.picker.confirm else '선택 검색' if self.picker else '명령 입력' if self.buffer.text.startswith('/') else '단어 추측'
        title = fit(' 입력 · ' + label + ' ', max(1, width - 4))
        left, line, right = ('+-', '-', '+') if self.ascii_only else ('╭─', '─', '╮')
        return [('class:input-border', left), ('class:input-label', title),
                ('class:input-border', line * max(0, width - get_cwidth(title) - 3) + right)]

    def _input_bottom(self):
        width = self.application.output.get_size().columns
        left, line, right = ('+', '-', '+') if self.ascii_only else ('╰', '─', '╯')
        return [('class:input-border', left + line * max(0, width - 2) + right)]

    def _key_help(self):
        width = self.application.output.get_size().columns
        text = '/ 명령 · Esc 취소 · Ctrl+D 종료' if width < 60 else '/ 명령  ·  ↑↓ 선택/입력 기록  ·  Esc 취소  ·  Ctrl+D 종료'
        if width < 35:
            text = '/help · Ctrl+D 종료'
        return [('class:muted', text)]

    def _status(self):
        parts = []
        if self.data:
            count = len(self.game.guesses)
            state = '정답!' if self.game.won else '포기한 회차' if self.game.given_up else f'추측 {count}회'
            saved = '저장 실패' if self.game.storage_warning else '저장됨' if count or self.game.finished else '첫 단어를 기다려요'
            if self.application and self.application.output.get_size().columns < 60:
                parts.append(f'{self.data.number}회 · {target_name(self.rank)} · {state}' + (' · 저장 실패' if self.game.storage_warning else ''))
            else:
                parts.append(f'{self.data.number}회 · 힌트 대상: {target_name(self.rank)} · {state} · {saved}')
        if self.busy:
            frames = '|/-\\' if self.ascii_only else '◐◓◑◒'
            animated = self.preferences['animation'] and not self.forced_no_animation
            frame = frames[int(asyncio.get_running_loop().time() * 5) % len(frames)] if animated else '·'
            request = f' #{self.work_exchange.number:02d}' if self.work_exchange else ''
            parts.append(f'{frame} 응답 준비{request} · {self.busy} · Ctrl+C 취소')
        if self.notice and not self.picker:
            parts.append(safe(self.notice))
        if get_today_round() != self.start_day:
            parts.append('새 회차가 시작됐어요. /round today 로 이동할 수 있어요.')
        return [('class:muted', '\n'.join(parts))]

    def _filtered(self):
        if not self.picker:
            return []
        query = '' if self.picker.confirm else self.buffer.text.strip().lower()
        return [item for item in self.picker.items if not query or query in (item[1] + ' ' + item[2]).lower()]

    def _choices(self):
        picker = self.picker
        if not picker:
            return []
        items = self._filtered()
        width = self.application.output.get_size().columns
        title = safe(picker.title) if picker.confirm else fit(picker.title, width - 2)
        result = [('class:title', ' ' + title + '\n')]
        if not items:
            return result + [('class:muted', ' 일치하는 항목이 없어요. Esc 로 돌아가세요.')]
        picker.selected = min(picker.selected, len(items) - 1)
        height = self.application.output.get_size().rows
        capacity = max(1, min(6, height - 8))
        start = max(0, picker.selected - min(3, capacity - 1))
        visible = items[start:start + capacity]
        for index, (_, label, description) in enumerate(visible, start):
            selected = index == picker.selected
            result.append(('class:selected' if selected else '', f' {">" if selected else " "} ' + fit(f'{label}  {description}', width - 4) + '\n'))
        if result:
            result[-1] = (result[-1][0], result[-1][1].rstrip('\n'))
        return result

    def _move(self, amount):
        items = self._filtered()
        if items:
            self.picker.selected = (self.picker.selected + amount) % len(items)

    def _choose(self):
        items = self._filtered()
        if not items:
            return
        picker = self.picker
        value = items[min(picker.selected, len(items) - 1)][0]
        self.picker = None
        self.buffer.reset()
        if picker.confirm:
            if value:
                self.application.create_background_task(self._confirmed(picker.action, exchange=picker.exchange, choice=items[min(picker.selected, len(items) - 1)][1]))
            else:
                self.application.create_background_task(self._confirmed(None, exchange=picker.exchange, choice='취소'))
        else:
            self.application.create_background_task(self.execute(value))

    def cancel_picker(self):
        picker = self.picker
        if not picker:
            return
        self.picker = None
        self.buffer.reset()
        self.notice = '취소했어요.'
        if self.application and self.application.is_running:
            self.application.create_background_task(self._confirmed(None, exchange=picker.exchange, choice='취소'))

    async def _confirmed(self, action, *, exchange=None, choice=None):
        token = CURRENT_EXCHANGE.set(exchange)
        try:
            if exchange and choice:
                await self.write(request_view(exchange, choice=choice, width=self.transcript_width(),
                                              plain=self.plain, ascii_only=self.ascii_only))
            if action is None:
                self.notice = '취소했어요.'
                await self.emit('요청을 취소했어요. 변경한 내용은 없어요.')
            else:
                await action()
        except asyncio.CancelledError:
            await self.emit('작업을 취소했어요.')
        except (KomantleError, GameError, OSError) as error:
            self.notice = str(error)
            await self.emit(str(error), error=True)
        finally:
            try:
                if exchange:
                    await self.flush_exchange(exchange)
            finally:
                CURRENT_EXCHANGE.reset(token)
        self.invalidate()

    async def choose(self, title, items):
        if self.plain:
            await self.emit(title + '\n' + '\n'.join(f'  {value} · {label} {description}' for value, label, description in items))
        else:
            self.buffer.reset()
            self.picker = Picker(title, items, exchange=CURRENT_EXCHANGE.get())
            await self.emit(title + '\n아래 선택창에서 고른 뒤 Enter를 눌러주세요.')
            self.invalidate()

    async def confirm(self, title, label, action):
        if self.plain:
            await self.emit(title + '\n대화형 확인이 필요해 취소했어요. 터미널에서 다시 실행해주세요.')
            return
        self.buffer.reset()
        self.picker = Picker(title, [(False, '취소', '계속 생각해볼게요'), (True, label, '')],
                             confirm=True, action=action, exchange=CURRENT_EXCHANGE.get())
        await self.emit(title + '\n아래 확인창에서 선택해주세요. 기본 선택은 취소예요.')
        self.invalidate()

    def require_game(self):
        if not self.game:
            raise KomantleError('회차 데이터가 필요해요. /refresh 또는 /round 로 불러와주세요.')

    def cancel_work(self):
        task = self.work
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self.work = None
        self.work_exchange = None
        self.busy = ''

    async def perform(self, title, action):
        self.cancel_work()
        task = asyncio.current_task()
        self.work, self.busy = task, title
        self.work_exchange = CURRENT_EXCHANGE.get()
        self.notice = ''
        self.invalidate()
        try:
            return await action()
        finally:
            if self.work is task:
                self.work, self.busy = None, ''
                self.work_exchange = None
            self.invalidate()

    def mount(self, data):
        game = self.sessions.get(data.number)
        if game is None:
            game = GameSession(data, state_dir=self.state_dir)
        else:
            game.rebind(data)
        self.sessions[data.number] = game
        self.data, self.game = data, game
        self.rank = 0
        self.revealed.clear()
        self.picker = None

    async def load(self, number=None, *, refresh=False):
        async def action():
            data = await run_io(self.repository.load, number, refresh=refresh)
            self.mount(data)
            status = f'{data.number}회 · {get_round_date(data.number)} · {data.source}'
            if self.game.guesses or self.game.finished:
                status += f' · 이어하기: {len(self.game.guesses)}번 추측'
            await self.emit(status)
            if self.game.won:
                await self.emit(f'이미 {len(self.game.guesses)}번 만에 맞힌 회차예요. /round 로 다른 회차를 선택할 수 있어요.')
            elif self.game.given_up:
                await self.emit(f'포기한 회차예요. 정답: {self.game.answer}')
            warnings = [self.repository.warning, self.game.storage_warning]
            if data.number != get_today_round() and not any(row['round'] == get_today_round() for row in self.repository.rounds):
                warnings.append('오늘 데이터 갱신 대기 · /round today 로 원본 조회를 시도할 수 있어요.')
            self.notice = ' · '.join(filter(None, warnings))
            if self.notice:
                await self.emit(self.notice)
        await self.perform('회차 데이터를 준비하고 있어요', action)

    async def execute(self, text):
        self.exchange_number += 1
        exchange = Exchange(self.exchange_number, text)
        token = CURRENT_EXCHANGE.set(exchange)
        try:
            await self.write(request_view(exchange, width=self.transcript_width(),
                                          plain=self.plain, ascii_only=self.ascii_only))
            if not text.startswith('/'):
                await self.guess(text)
                return
            name, args = parse(text)
            if name in ('quit', 'clear', 'help', 'status', 'links', 'refresh', 'giveup') and args:
                raise KomantleError(f'/{name} 명령에는 인자가 필요하지 않아요.')
            await getattr(self, 'cmd_' + name)(args)
        except asyncio.CancelledError:
            await self.emit('작업을 취소했어요.')
        except (KomantleError, GameError, OSError) as error:
            self.notice = str(error)
            await self.emit(str(error), error=True)
        finally:
            try:
                await self.flush_exchange(exchange)
            finally:
                CURRENT_EXCHANGE.reset(token)
                self.invalidate()

    async def guess(self, text):
        self.require_game()
        game = self.game
        async def action():
            result = await run_io(game.prepare, text)
            if self.closed or self.game is not game:
                return
            game.commit(result)
            rank = '정답!' if result.correct else f'{result.rank}위' if result.rank is not None else '순위 미제공'
            await self.emit(f'{len(game.guesses)}번째 · {result.word} · 유사도 {result.similarity:.2f} · {rank}')
            if game.won:
                await self.emit(Text(f'(\\_/)  정답이에요! {len(game.guesses)}번 만에 맞혔어요. /round 로 다음 도전을 시작해보세요.', style='green'))
            elif result.similarity == max(row.similarity for row in game.guesses) and len(game.guesses) > 1:
                await self.emit('지금까지 가장 가까운 단어예요.')
            self.notice = game.storage_warning
            if self.notice:
                await self.emit(self.notice, error=True)
        await self.perform('단어를 채점하고 있어요', action)

    async def cmd_help(self, args):
        await self.emit(help_table())

    async def cmd_round(self, args):
        if len(args) > 1:
            raise KomantleError('사용 예: /round 1667 또는 /round today')
        if not args:
            if self.repository.manifest is None:
                async def action():
                    await run_io(self.repository.load_manifest)
                await self.perform('회차 목록을 불러오고 있어요', action)
            items = [('/round today', '오늘', '오늘 회차 · 보관되지 않았으면 원본 조회')]
            items += [(f'/round {row["round"]}', f'{row["round"]}회', row['date']) for row in reversed(self.repository.rounds)]
            await self.choose('어떤 회차를 풀어볼까요? 날짜·회차로 검색하세요.', items)
            return
        value = {'오늘': 'today', '최신': 'latest'}.get(args[0], args[0])
        if value == 'today': number = get_today_round()
        elif value == 'latest':
            if not self.repository.rounds:
                raise KomantleError('보관된 회차가 없어요. /refresh 로 목록을 갱신해주세요.')
            number = self.repository.rounds[-1]['round']
        else: number = integer(value, 0, get_today_round(), '회차')
        self.picker = None
        await self.load(number)

    async def cmd_rank(self, args):
        self.require_game()
        if len(args) > 1:
            raise KomantleError('사용 예: /rank 50 (0은 정답)')
        if not args:
            await self.choose('힌트 대상 순위 · 숫자로 검색하세요. 0은 정답이에요.',
                              [(f'/rank {entry["word_id"]}', target_name(entry['word_id']), '') for entry in sorted(self.data.word_list, key=lambda row: row['word_id'])])
            return
        rank = integer(args[0], 0, 1000, '순위')
        self.data.get_length(rank)
        if self.busy == '힌트를 준비하고 있어요':
            self.cancel_work()
        self.rank = rank
        self.revealed.clear()
        self.notice = '힌트 대상을 바꿨어요. 추측은 계속 현재 회차의 정답을 향해 진행해요.'
        await self.emit(f'힌트 대상: {target_name(rank)} · 공개한 힌트를 모두 닫았어요.')

    async def cmd_hint(self, args):
        self.require_game()
        if not args:
            await self.choose('어떤 힌트가 필요하세요?', [(f'/hint {kind}', label, '확인 후 공개' if kind == 'word' else '') for kind, label in HINTS.items()])
            return
        kind = hint_kind(args[0])
        if kind == 'char' and len(args) == 1:
            await self.choose('어느 위치의 글자를 공개할까요?', [(f'/hint char {position}', f'{position}번째 글자', '') for position in range(1, self.data.get_length(self.rank) + 1)])
            return
        if len(args) != (2 if kind == 'char' else 1):
            raise KomantleError('사용 예: /hint char 2' if kind == 'char' else f'사용 예: /hint {kind}')
        position = integer(args[1], 1, self.data.get_length(self.rank), '글자 위치') if kind == 'char' else 1
        data, rank = self.data, self.rank
        async def reveal():
            async def action():
                value = await run_io(hint_text, data, rank, kind, position)
                if self.data is not data or self.rank != rank or self.closed:
                    return
                self.revealed[kind] = value
                if self.plain:
                    await self.emit(f'{HINTS[kind]}: {value}\n텍스트 모드에서는 이미 출력한 힌트를 다시 숨길 수 없어요.')
                else:
                    self.notice = f'{HINTS[kind]} 힌트를 공개했어요. /hide 로 숨길 수 있어요.'
                    await self.emit(f'{data.number}회 · {target_name(rank)}의 {HINTS[kind]} 힌트를 공개했어요.\n값은 아래 힌트 패널에서 확인하세요.')
            await self.perform('힌트를 준비하고 있어요', action)
        if kind == 'word':
            await self.confirm(f'{data.number}회 · {target_name(rank)}의 전체 단어를 공개할까요?', '단어 공개하기', reveal)
        else:
            await reveal()

    async def cmd_hide(self, args):
        if self.busy == '힌트를 준비하고 있어요':
            self.cancel_work()
        if len(args) > 1:
            raise KomantleError('사용 예: /hide 또는 /hide initial')
        if not args or args[0] in ('all', '전체'):
            self.revealed.clear()
        else:
            self.revealed.pop(hint_kind(args[0]), None)
        self.notice = '힌트를 숨겼어요.'
        if self.plain:
            await self.emit('공개 상태를 초기화했어요. 이미 출력된 텍스트는 남아 있어요.')
        else:
            await self.emit('힌트 패널의 공개 상태를 닫았어요.')

    async def cmd_history(self, args):
        self.require_game()
        recent, page = False, 1
        seen = set()
        while args:
            flag = args[0]
            if flag not in ('--sort', '--page') or flag in seen or len(args) < 2:
                raise KomantleError('사용 예: /history --sort recent --page 1')
            seen.add(flag)
            value, args = args[1], args[2:]
            if flag == '--sort':
                if value not in ('similarity', 'recent'):
                    raise KomantleError('정렬은 similarity 또는 recent를 사용해주세요.')
                recent = value == 'recent'
            else:
                page = integer(value, 1, 50, '페이지')
        await self.emit(history_table(self.game, recent=recent, page=page))

    async def cmd_giveup(self, args):
        self.require_game()
        self.cancel_work()
        if self.game.finished:
            raise GameError('이미 마친 회차예요. /round 로 다른 회차를 선택해주세요.')
        game = self.game
        async def action():
            if self.game is game:
                answer = game.give_up()
                await self.emit(f'이번 회차를 마쳤어요. 정답: {answer}')
                self.notice = game.storage_warning or '다음 회차에서도 만나요. /round'
        await self.confirm(f'{game.number}회 정답을 공개하고 포기할까요?', '정답 보고 포기하기', action)

    async def cmd_records(self, args):
        if not args or args == ['delete']:
            await self.choose('어떤 기록을 삭제할까요?', [('/records delete current', '현재 회차', '추측 기록과 정답·포기 상태'), ('/records delete all', '전체 회차', '이 CLI에 저장된 게임 기록')])
            return
        if len(args) != 2 or args[0] != 'delete' or args[1] not in ('current', 'all', '현재', '전체'):
            raise KomantleError('사용 예: /records delete current 또는 /records delete all')
        self.cancel_work()
        current = args[1] in ('current', '현재')
        if current:
            self.require_game()
        number = self.data.number if current else None
        count = len(record_files(self.state_dir, number))
        data = self.data
        async def action():
            try:
                removed = delete_records(self.state_dir, number)
            finally:
                targets = [number] if current else list(self.sessions)
                for target in targets:
                    session = self.sessions.get(target)
                    if session and not session.path.exists():
                        self.sessions.pop(target)
                if data is self.data and data is not None:
                    self.mount(data)
            await self.emit(f'{removed}개 회차 기록을 삭제했어요. 첫 단어부터 다시 시작해보세요.')
        label = f'{number}회' if current else '전체 회차'
        await self.confirm(f'{label} 기록 {count}개를 삭제할까요? 추측·정답·포기 상태가 지워지며 되돌릴 수 없어요.', '기록 삭제하기', action)

    async def cmd_status(self, args):
        lines = [f'게임 기록: {self.state_dir}', f'데이터 캐시: {self.repository.cache_dir}', '웹 브라우저의 기록과 CLI 기록은 별도로 저장돼요.']
        if self.data:
            lines[:0] = [f'{self.data.number}회 · {get_round_date(self.data.number)} · {self.data.source}',
                         f'수집/조회 시각: {self.data.collected_at or "알 수 없음"} (표기된 시간대 기준)',
                         f'힌트 대상: {target_name(self.rank)} · 추측 {len(self.game.guesses)}회',
                         '보관된 단어는 오프라인 채점 가능 · 미보관 단어는 원본 API의 채점 기간에 따라 달라져요.']
            if self.game.storage_warning: lines.append(self.game.storage_warning)
        else:
            lines.insert(0, '데이터를 준비하지 못했어요. /refresh 로 다시 시도해주세요.')
        await self.emit('\n'.join(lines))

    async def cmd_links(self, args):
        await self.emit('원본 게임: https://semantle-ko.newsjel.ly/\nGitHub: https://github.com/Testrapod/komantle-helper')

    async def cmd_refresh(self, args):
        await self.load(self.data.number if self.data else None, refresh=True)

    async def cmd_settings(self, args):
        if not args:
            await self.choose('화면 설정', [(f'/settings {key} {"off" if value else "on"}', label, '켜짐 → 끄기' if value else '꺼짐 → 켜기') for key, label, value in [('color', '색상', not self.no_color), ('animation', '로딩 효과', self.preferences['animation'] and not self.forced_no_animation)]])
            return
        if len(args) != 2 or args[0] not in self.preferences or args[1] not in ('on', 'off'):
            raise KomantleError('사용 예: /settings color off 또는 /settings animation off')
        key, value = args[0], args[1] == 'on'
        self.preferences[key] = value
        self.console.no_color = self.no_color
        try:
            atomic_write(self.state_dir / 'settings.json', json_bytes(self.preferences))
        except OSError:
            raise KomantleError('현재 실행에 설정을 적용했지만 파일에 저장하지 못했어요.')
        await self.emit('화면 설정을 저장했어요.' + (' 실행 옵션과 NO_COLOR가 설정보다 우선해요.' if self.forced_no_color or self.forced_no_animation else ''))

    async def cmd_clear(self, args):
        if not self.plain:
            await run_in_terminal(self.console.clear)
        await self.emit('화면을 정리했어요. 게임 기록은 그대로예요.')

    async def cmd_quit(self, args):
        await self.emit('프로그램을 종료할게요.')
        exchange = CURRENT_EXCHANGE.get()
        if exchange:
            await self.flush_exchange(exchange)
        self.close()

    def close(self):
        self.closed = True
        self.cancel_work()
        self.revealed.clear()
        self.picker = None
        if self.application and self.application.is_running:
            self.application.exit()

    async def _refresh_cached_manifest(self):
        try:
            await run_io(self.repository.load_manifest, refresh=True)
            self.notice = self.repository.warning
            if self.data and self.data.number != get_today_round() and any(row['round'] == get_today_round() for row in self.repository.rounds):
                self.notice = '오늘 회차가 준비됐어요. /round today 로 이동할 수 있어요.'
        except KomantleError as error:
            self.notice = str(error)
        self.invalidate()

    async def run(self, number=None):
        self.console.print(banner(self.ascii_only))
        if self.config_warning:
            await self.emit(self.config_warning)
        if self.plain:
            try:
                await self.load(number)
            except (KomantleError, GameError) as error:
                await self.emit(str(error), error=True)
            while not self.closed:
                try:
                    text = input('> ').strip()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    await self.emit('입력을 취소했어요.')
                    continue
                if text:
                    await self.execute(text)
        else:
            async def start():
                try:
                    await self.load(number)
                    if self.repository.used_cached_manifest is True and not self.repository.archive_dir:
                        self.application.create_background_task(self._refresh_cached_manifest())
                except (KomantleError, GameError, OSError) as error:
                    self.notice = str(error)
                    await self.emit(str(error), error=True)
            async def animate():
                while not self.closed:
                    await asyncio.sleep(.2)
                    if self.busy and self.preferences['animation'] and not self.forced_no_animation:
                        self.invalidate()
            def pre_run():
                self.application.create_background_task(start())
                self.application.create_background_task(animate())
            await self.application.run_async(pre_run=pre_run)
        self.closed = True
        self.revealed.clear()
        warning = self.game.storage_warning if self.game else ''
        await self.emit(warning or '(\\_/)  다음에 또 만나요!')
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='꼬맨틀 헬퍼 · 힌트와 게임 · / 로 명령 찾기')
    parser.add_argument('--version', action='version', version=f'komantle-helper {__version__}')
    parser.add_argument('--round', type=int, dest='round_number', help='시작 회차 (기본: 오늘 또는 최신 보관 회차)')
    parser.add_argument('--archive-dir', type=Path, help='네트워크 대신 로컬 아카이브 사용')
    parser.add_argument('--cache-dir', type=Path, help='데이터 캐시 폴더')
    parser.add_argument('--state-dir', type=Path, help='게임 기록과 화면 설정 폴더')
    parser.add_argument('--plain', action='store_true', help='커서 제어 없는 텍스트 모드')
    parser.add_argument('--no-color', action='store_true', help='색상 끄기')
    parser.add_argument('--no-animation', action='store_true', help='로딩 애니메이션 끄기')
    parser.add_argument('--ascii', action='store_true', dest='ascii_only', help='이모지 얼굴과 입력 프롬프트에 ASCII 사용')
    args = parser.parse_args(argv)
    if args.round_number is not None and not 0 <= args.round_number <= get_today_round():
        parser.error('회차는 오늘 이하의 0 이상의 정수여야 합니다.')
    plain = args.plain or not (sys.stdin.isatty() and sys.stdout.isatty()) or os.environ.get('TERM') == 'dumb'
    app = TerminalApp(Repository(archive_dir=args.archive_dir, cache_dir=args.cache_dir), state_dir=args.state_dir,
                      plain=plain, no_color=args.no_color, no_animation=args.no_animation, ascii_only=args.ascii_only)
    try:
        return asyncio.run(app.run(args.round_number))
    except (EOFError, KeyboardInterrupt):
        return 0
