"""명령·힌트·확인·취소와 실제 키 입력의 통합 검증."""

import asyncio
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from prompt_toolkit.document import Document
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.data_structures import Size
from rich.console import Console

from komantle_helper.cli.app import TerminalApp, main
from komantle_helper.cli.commands import CommandCompleter, parse
from komantle_helper.core import KomantleError, RoundData, Word
from komantle_helper.game import GameSession, Guess, delete_records


def sample(number=1667):
    return RoundData(number, [{'word_id': 0, 'word': Word('사과', pos='명사'), 'similarity': 100.0},
                             {'word_id': 1, 'word': Word('과일', pos='명사'), 'similarity': 51.25},
                             {'word_id': 1000, 'word': Word('까치', pos='명사'), 'similarity': 12.0}],
                     source='테스트 아카이브', collected_at='2026-10-24T10:00:00+09:00')


class SizedOutput(DummyOutput):
    columns, rows = 80, 24

    def get_size(self):
        return Size(rows=self.rows, columns=self.columns)


class CommandsTests(unittest.TestCase):
    def test_aliases_and_actionable_unknown_command(self):
        self.assertEqual(parse('/힌트 초성'), ('hint', ['초성']))
        self.assertEqual(parse('/기록삭제 현재'), ('records', ['delete', '현재']))
        with self.assertRaisesRegex(KomantleError, '/history'):
            parse('/hstory')
        with self.assertRaisesRegex(KomantleError, '따옴표'):
            parse('/round "')

    def test_completion_uses_only_commands_and_metadata(self):
        completer = CommandCompleter(lambda: [{'round': 1667, 'date': '2026-10-24'}])
        complete = lambda text: list(completer.get_completions(Document(text), CompleteEvent()))
        self.assertIn('/hint', [row.text for row in complete('/힌')])
        self.assertIn('initial', [row.text for row in complete('/hint ')] )
        self.assertIn('1667', [row.text for row in complete('/round ')] )
        for text in ('/', '/hint ', '/rank ', '/round '):
            self.assertNotIn('사과', str(complete(text)))
        self.assertEqual(complete('사'), [])

    def test_entrypoint_rejects_legacy_mode_and_future_round(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                main(['--play'])
            with self.assertRaises(SystemExit):
                main(['--round', '9999999'])


class CLITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.stream = io.StringIO()
        self.repository = Mock(rounds=[{'round': 1667, 'date': '2026-10-24'}], manifest={'rounds': []}, warning='', cache_dir=self.state / 'cache')
        self.repository.load.side_effect = lambda number=None, **kwargs: sample(number or 1667)
        self.pipe_context = create_pipe_input()
        self.pipe = self.pipe_context.__enter__()
        self.addCleanup(self.pipe_context.__exit__, None, None, None)
        self.output = SizedOutput()
        self.app = TerminalApp(self.repository, state_dir=self.state, console=Console(file=self.stream, width=80, no_color=True),
                               no_color=True, no_animation=True, input=self.pipe, output=self.output)
        self.app.mount(sample())

    async def confirm(self, approve):
        picker = self.app.picker
        self.assertTrue(picker.confirm)
        self.assertEqual(picker.selected, 0)
        self.app.picker = None
        if approve:
            await self.app._confirmed(picker.action, exchange=picker.exchange, choice='승인')

    async def test_all_hints_hide_and_target_change_without_transcript_spoilers(self):
        for command, kind, value in [('/hint length', 'length', '2글자'), ('/힌트 품사', 'pos', '명사'),
                                     ('/hint initial', 'initial', 'ㅅㄱ'), ('/hint similarity', 'similarity', '100.00'),
                                     ('/hint char 2', 'char', '2번째 · 과')]:
            await self.app.execute(command)
            self.assertEqual(self.app.revealed[kind], value)
        self.assertNotIn('ㅅㄱ', self.stream.getvalue())
        self.assertNotIn('사과', self.stream.getvalue())
        await self.app.execute('/hide initial')
        self.assertNotIn('initial', self.app.revealed)
        await self.app.execute('/rank 1')
        self.assertEqual(self.app.rank, 1)
        self.assertEqual(self.app.revealed, {})
        await self.app.execute('과일')
        self.assertEqual(self.app.game.guesses[0].rank, 1)
        self.assertFalse(self.app.game.won)

    async def test_word_reveal_requires_confirmation_and_does_not_give_up(self):
        await self.app.execute('/hint word')
        await self.confirm(False)
        self.assertNotIn('word', self.app.revealed)
        await self.app.execute('/hint word')
        await self.confirm(True)
        self.assertEqual(self.app.revealed['word'], '사과')
        self.assertFalse(self.app.game.given_up)
        self.assertNotIn('사과', self.stream.getvalue())

    async def test_invalid_character_preserves_revealed_value(self):
        await self.app.execute('/hint char 1')
        await self.app.execute('/hint char 0')
        self.assertEqual(self.app.revealed['char'], '1번째 · 사')
        self.assertIn('1~2', self.stream.getvalue())

    async def test_round_switch_resumes_records_and_resets_hints(self):
        await self.app.execute('과일')
        await self.app.execute('/hint initial')
        await self.app.execute('/round 1666')
        self.assertEqual(self.app.game.guesses, [])
        self.assertEqual(self.app.revealed, {})
        await self.app.execute('/round 1667')
        self.assertEqual(len(self.app.game.guesses), 1)

    async def test_guess_duplicate_win_and_history(self):
        await self.app.execute('과일')
        await self.app.execute('과일')
        self.assertEqual(len(self.app.game.guesses), 1)
        await self.app.execute('사과')
        self.assertTrue(self.app.game.won)
        await self.app.execute('/history')
        self.assertIn('정답!', self.stream.getvalue())
        self.assertIn('2번 만에', self.stream.getvalue())

    async def test_giveup_cancel_and_approve_restore(self):
        await self.app.execute('/giveup')
        await self.confirm(False)
        self.assertFalse(self.app.game.given_up)
        await self.app.execute('/포기')
        await self.confirm(True)
        self.assertTrue(GameSession(sample(), state_dir=self.state).given_up)

    async def test_current_and_all_deletion_preserve_other_files(self):
        await self.app.execute('과일')
        other = GameSession(sample(1666), state_dir=self.state)
        other.submit('과일')
        keep = self.state / 'settings.json'
        keep.write_text('{}')
        (self.state / 'game-backup.json').write_text('keep')
        await self.app.execute('/records delete current')
        await self.confirm(False)
        self.assertEqual(len(self.app.game.guesses), 1)
        await self.app.execute('/records delete current')
        await self.confirm(True)
        self.assertEqual(len(self.app.game.guesses), 0)
        self.assertTrue(other.path.exists())
        await self.app.execute('/records delete all')
        await self.confirm(True)
        self.assertFalse(other.path.exists())
        self.assertTrue(keep.exists())
        self.assertTrue((self.state / 'game-backup.json').exists())

    async def test_deletion_failure_is_not_reported_as_success(self):
        await self.app.execute('과일')
        await self.app.execute('/records delete current')
        with patch('pathlib.Path.unlink', side_effect=PermissionError('denied')):
            await self.confirm(True)
        self.assertIn('삭제 실패', self.stream.getvalue())
        self.assertEqual(len(self.app.game.guesses), 1)

    async def test_settings_persist_and_no_color_override_wins(self):
        await self.app.execute('/settings color on')
        self.assertTrue(self.app.no_color)
        config = json.loads((self.state / 'settings.json').read_text())
        self.assertTrue(config['color'])
        await self.app.execute('/settings animation off')
        self.assertFalse(self.app.preferences['animation'])

    async def test_refresh_failure_preserves_game_and_hints(self):
        await self.app.execute('과일')
        await self.app.execute('/hint initial')
        self.repository.load.side_effect = KomantleError('연결 실패')
        await self.app.execute('/refresh')
        self.assertEqual(len(self.app.game.guesses), 1)
        self.assertEqual(self.app.revealed['initial'], 'ㅅㄱ')

    async def test_unknown_slash_and_bad_arguments_never_score(self):
        scorer = Mock()
        self.app.game.scorer = scorer
        for text in ('/hstory', '/hint char', '/rank -1', '/history --sort nope', '/quit extra'):
            await self.app.execute(text)
        scorer.assert_not_called()
        self.assertEqual(self.app.game.guesses, [])
        self.assertFalse(self.app.closed)

    async def test_late_score_after_cancellation_is_not_saved(self):
        started, finish = threading.Event(), threading.Event()
        def score(number, word):
            started.set()
            finish.wait(2)
            return Guess(word, 3.0, None, False)
        self.app.game.scorer = score
        task = asyncio.create_task(self.app.execute('바다'))
        await asyncio.to_thread(started.wait, 1)
        self.app.cancel_work()
        finish.set()
        await task
        await asyncio.sleep(.05)
        self.assertEqual(self.app.game.guesses, [])
        self.assertFalse(self.app.game.path.exists())

    async def test_hiding_cancels_pending_hint(self):
        started, finish = threading.Event(), threading.Event()
        def hint(*args):
            started.set()
            finish.wait(2)
            return '명사'
        with patch('komantle_helper.cli.app.hint_text', side_effect=hint):
            task = asyncio.create_task(self.app.execute('/hint pos'))
            await asyncio.to_thread(started.wait, 1)
            await self.app.execute('/hide')
            finish.set()
            await task
            await asyncio.sleep(.05)
        self.assertEqual(self.app.revealed, {})

    async def test_plain_mode_confirms_by_cancelling_and_contains_no_ansi(self):
        self.app.plain = True
        await self.app.execute('/hint word')
        await self.app.execute('/giveup')
        await self.app.execute('/records delete all')
        self.assertIsNone(self.app.picker)
        self.assertFalse(self.app.game.given_up)
        self.assertNotIn('사과', self.stream.getvalue())
        self.assertNotIn('\x1b', self.stream.getvalue())
        self.assertIn('대화형 확인', self.stream.getvalue())

    async def wait_for(self, predicate):
        for _ in range(100):
            if predicate(): return
            await asyncio.sleep(.02)
        self.fail('터미널 이벤트를 기다리다 시간 초과')

    async def test_live_input_palette_confirmation_escape_and_eof(self):
        task = asyncio.create_task(self.app.run(1667))
        try:
            await self.wait_for(lambda: self.app.application.is_running and not self.app.busy and self.repository.load.called)
            self.pipe.send_text('/')
            await self.wait_for(lambda: self.app.buffer.complete_state is not None)
            self.assertGreater(len(self.app.buffer.complete_state.completions), 5)
            self.pipe.send_text('\x03/hint word\r')
            await self.wait_for(lambda: self.app.picker is not None)
            self.pipe.send_text('\r')  # 기본 선택인 취소
            await self.wait_for(lambda: self.app.picker is None)
            self.assertNotIn('word', self.app.revealed)
            self.pipe.send_text('/hint word\r')
            await self.wait_for(lambda: self.app.picker is not None)
            self.pipe.send_text('\x1b[B\r')
            await self.wait_for(lambda: 'word' in self.app.revealed)
            self.assertEqual(self.app.revealed['word'], '사과')
            self.pipe.send_text('/hide\r')
            await self.wait_for(lambda: not self.app.revealed)
            self.pipe.send_text('\x04')
            await asyncio.wait_for(task, 3)
            self.assertTrue(self.app.closed)
        finally:
            if not task.done():
                self.app.close()
                await task

    async def test_narrow_render_resize_and_hint_hidden_from_current_screen(self):
        self.output.columns, self.output.rows = 40, 10
        def screen_text():
            screen = self.app.application.renderer.last_rendered_screen
            if not screen:
                return ''
            return '\n'.join(''.join(row[x].char for x in sorted(row)) for _, row in sorted(screen.data_buffer.items()))
        task = asyncio.create_task(self.app.run(1667))
        try:
            await self.wait_for(lambda: self.repository.load.called and not self.app.busy)
            self.pipe.send_text('/hint initial\r')
            await self.wait_for(lambda: 'ㅅㄱ' in screen_text())
            self.assertIn('›', screen_text())
            self.pipe.send_text('/hide\r')
            await self.wait_for(lambda: not self.app.revealed and 'ㅅㄱ' not in screen_text())
            self.pipe.send_text('/hint word\r')
            await self.wait_for(lambda: '단어 공개하기' in screen_text())
            self.assertIn('취소', screen_text())
            self.pipe.send_text('\x1b[B\r')
            await self.wait_for(lambda: '사과' in screen_text())
            for columns in (80, 120):
                self.output.columns = columns
                self.app.invalidate()
                await asyncio.sleep(.05)
                self.assertIn('사과', screen_text())
            self.pipe.send_text('/hide\r')
            await self.wait_for(lambda: not self.app.revealed and '사과' not in screen_text())
            self.pipe.send_text('\x04')
            await asyncio.wait_for(task, 3)
        finally:
            if not task.done():
                self.app.close()
                await task

    async def test_bracketed_multiline_paste_does_not_submit_commands(self):
        task = asyncio.create_task(self.app.run(1667))
        try:
            await self.wait_for(lambda: self.repository.load.called and not self.app.busy)
            self.pipe.send_text('\x1b[200~과일\n/quit\x1b[201~')
            await self.wait_for(lambda: '/quit' in self.app.buffer.text)
            self.pipe.send_text('\r')
            await asyncio.sleep(.05)
            self.assertFalse(self.app.closed)
            self.assertEqual(self.app.game.guesses, [])
            self.pipe.send_text('\x03\x04')
            await asyncio.wait_for(task, 3)
        finally:
            if not task.done():
                self.app.close()
                await task

    async def test_unsaved_progress_survives_refresh_and_round_switch(self):
        with patch('komantle_helper.game.os.replace', side_effect=OSError('full')):
            await self.app.execute('과일')
        self.assertTrue(self.app.game.storage_warning)
        await self.app.execute('/refresh')
        self.assertEqual(len(self.app.game.guesses), 1)
        await self.app.execute('/round 1666')
        await self.app.execute('/round 1667')
        self.assertEqual(len(self.app.game.guesses), 1)
        self.assertTrue(self.app.game.storage_warning)
        await self.app.execute('/records delete current')
        await self.confirm(True)
        self.assertEqual(self.app.game.guesses, [])

    async def test_selected_picker_item_stays_visible_at_low_height(self):
        self.output.columns, self.output.rows = 40, 10
        await self.app.execute('/rank')
        self.app._move(1)
        self.app._move(1)
        selected = [value for style, value in self.app._choices() if style == 'class:selected']
        self.assertEqual(len(selected), 1)
        self.assertIn('1000위', selected[0])

    async def test_transcript_preserves_inputs_and_groups_their_responses(self):
        await self.app.execute('까치')
        await self.app.execute('과일')
        output = self.stream.getvalue()
        self.assertEqual(output.count('나 · 추측 #01'), 1)
        self.assertEqual(output.count('나 · 추측 #02'), 1)
        self.assertEqual(output.count('꼬맨틀 헬퍼 · 응답 #02'), 1)
        second = output[output.index('나 · 추측 #02'):]
        self.assertIn('과일', second)
        self.assertIn('51.25', second)
        self.assertIn('지금까지 가장 가까운', second)
        await self.app.execute('/history')
        self.assertIn('나 · 명령 #03', self.stream.getvalue())
        self.assertIn('꼬맨틀 헬퍼 · 응답 #03', self.stream.getvalue())

    async def test_confirmation_response_keeps_original_command_number(self):
        await self.app.execute('/hint word')
        self.assertIn('꼬맨틀 헬퍼 · 확인 대기 #01', self.stream.getvalue())
        await self.confirm(True)
        output = self.stream.getvalue()
        self.assertIn('나 · 확인 #01', output)
        self.assertIn('꼬맨틀 헬퍼 · 응답 #01', output)
        self.assertNotIn('사과', output)
        self.assertEqual(self.app.revealed['word'], '사과')

    async def test_interleaved_response_keeps_its_own_command_number(self):
        started, finish = threading.Event(), threading.Event()
        def score(number, word):
            started.set()
            finish.wait(2)
            return Guess(word, 3.0, None, False)
        self.app.game.scorer = score
        task = asyncio.create_task(self.app.execute('바다'))
        try:
            await asyncio.to_thread(started.wait, 1)
            await self.app.execute('/status')
            finish.set()
            await task
        finally:
            finish.set()
            await task
        output = self.stream.getvalue()
        self.assertLess(output.index('꼬맨틀 헬퍼 · 응답 #02'), output.index('꼬맨틀 헬퍼 · 응답 #01'))
        delayed = output[output.index('꼬맨틀 헬퍼 · 응답 #01'):]
        self.assertIn('바다', delayed)
        self.assertIn('3.00', delayed)

    async def test_errors_and_hidden_hint_acknowledgements_are_explicit(self):
        await self.app.execute('/rank -1')
        self.assertIn('나 · 명령 #01', self.stream.getvalue())
        self.assertIn('꼬맨틀 헬퍼 · 오류 #01', self.stream.getvalue())
        await self.app.execute('/hint initial')
        output = self.stream.getvalue()
        self.assertIn('꼬맨틀 헬퍼 · 응답 #02', output)
        self.assertIn('힌트를 공개했어요', output)
        self.assertNotIn('ㅅㄱ', output)
        await self.app.execute('/hide')
        self.assertIn('꼬맨틀 헬퍼 · 응답 #03', self.stream.getvalue())
        self.assertIn('공개 상태를 닫았어요', self.stream.getvalue())


class WorkerShutdownTests(unittest.TestCase):
    def test_cancelled_network_worker_does_not_hold_process_open(self):
        import subprocess
        import sys
        code = '''
import asyncio
import time
from komantle_helper.cli.workers import run_io
async def main():
    task = asyncio.create_task(run_io(time.sleep, 10))
    await asyncio.sleep(.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
asyncio.run(main())
'''
        result = subprocess.run([sys.executable, '-c', code], timeout=3, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
