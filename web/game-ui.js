import { Game } from './game.js';
import { GUESS_API_URL } from './config.js';

const $ = id => document.getElementById(id);

export function createGameUI() {
  let game = null;
  const message = (text, error = false) => { $('game-message').textContent = text; $('game-message').classList.toggle('is-error', error); };
  function render() {
    const ready = Boolean(game && !game.finished && !game.pending);
    $('guess-word').disabled = !ready; $('guess-submit').disabled = !ready; $('give-up').disabled = !ready;
    $('game-count').textContent = `${game?.guesses.length || 0}번 추측`;
    $('game-warning').textContent = game?.warning || '';
    $('game-warning').hidden = !game?.warning;
    $('guess-rows').replaceChildren();
    const guesses = game?.guesses || [];
    const ordered = guesses.map((guess, index) => ({ ...guess, attempt: index + 1 })).sort((a, b) => b.similarity - a.similarity || b.attempt - a.attempt);
    for (const guess of ordered) {
      const row = document.createElement('tr');
      if (guess.attempt === guesses.length) row.classList.add('latest-guess');
      if (guess.correct) row.classList.add('correct-guess');
      for (const value of [guess.attempt, guess.word, guess.similarity.toFixed(2), guess.correct ? '정답!' : guess.rank === null ? '순위 미제공' : `${guess.rank}위`]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      $('guess-rows').append(row);
    }
    $('game-history').hidden = !guesses.length;
    $('game-empty').hidden = Boolean(guesses.length);
    if (game?.won) message(`정답이에요! ${guesses.length}번 만에 맞혔어요. 다음 회차에서도 만나요.`);
    else if (game?.givenUp) message(`이번 회차를 마쳤어요. 정답은 ‘${game.answer}’입니다.`);
  }
  $('guess-form').addEventListener('submit', async event => {
    event.preventDefault();
    const current = game;
    if (!current || current.pending || current.finished) return;
    try {
      const pending = current.submit($('guess-word').value);
      render(); message('단어를 채점하고 있어요…');
      const guess = await pending;
      if (current !== game) return;
      $('guess-word').value = '';
      message(`${guess.word} · 유사도 ${guess.similarity.toFixed(2)} · ${guess.rank === null ? '순위 미제공' : guess.correct ? '정답!' : `${guess.rank}위`}`);
    } catch (error) { if (current === game) message(error.message, true); }
    finally { if (current === game) { render(); if (!game.finished) $('guess-word').focus(); } }
  });
  $('give-up').addEventListener('click', () => { if (game && !game.finished && !game.pending) $('give-up-dialog').showModal(); });
  $('give-up-dialog').addEventListener('close', () => {
    if ($('give-up-dialog').returnValue === 'giveup' && game && !game.pending) { game.giveUp(); render(); }
  });
  function clear() {
    game?.close(); game = null;
    if ($('give-up-dialog').open) $('give-up-dialog').close('cancel');
    $('guess-word').value = '';
    message('회차 데이터를 불러오면 게임을 시작할 수 있어요.'); render();
  }
  clear();
  return {
    clear,
    mount(data) {
      clear(); game = new Game(data, { apiURL: GUESS_API_URL });
      message('첫 단어를 입력해보세요. 유사도가 높을수록 정답과 가까워요.');
      render();
    },
  };
}
