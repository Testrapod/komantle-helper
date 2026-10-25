import { Game, deleteGameRecords } from './game.js';
import { GUESS_API_URL } from './config.js';

const $ = id => document.getElementById(id);

export function createGameUI() {
  let game = null;
  let roundData = null;
  let deletion = null;
  const message = (text, error = false) => { $('game-message').textContent = text; $('game-message').classList.toggle('is-error', error); };
  function render() {
    const ready = Boolean(game && !game.finished && !game.pending);
    $('guess-word').disabled = !ready; $('guess-submit').disabled = !ready; $('give-up').disabled = !ready;
    $('delete-round-records').disabled = !game;
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
  for (const scope of ['round', 'all']) {
    $(`delete-${scope}-records`).addEventListener('click', () => {
      if (scope === 'round' && !game) return;
      deletion = { scope, game };
      $('delete-records-title').textContent = scope === 'round' ? `${game.round}회 기록을 삭제할까요?` : '전체 회차 기록을 삭제할까요?';
      $('delete-records-description').textContent = scope === 'round'
        ? '이 회차의 추측 기록과 정답·포기 상태를 삭제하고 처음부터 다시 시작해요. 다른 회차의 기록은 남아요. 삭제한 기록은 되돌릴 수 없어요.'
        : '이 브라우저에 저장된 모든 회차의 추측 기록과 정답·포기 상태를 삭제해요. 삭제한 기록은 되돌릴 수 없어요.';
      $('delete-records-dialog').showModal();
    });
  }
  $('delete-records-dialog').addEventListener('close', () => {
    const target = deletion;
    deletion = null;
    if ($('delete-records-dialog').returnValue !== 'delete' || !target || target.game !== game) return;
    try {
      deleteGameRecords(target.scope === 'round' ? game.round : null);
      if (roundData) mount(roundData);
      message(target.scope === 'round' ? '이 회차 기록을 삭제했어요. 첫 단어부터 다시 시작해보세요.' : '전체 회차 기록을 삭제했어요. 첫 단어부터 다시 시작해보세요.');
    } catch { message('기록을 삭제하지 못했어요. 브라우저의 저장소 설정을 확인하고 다시 시도해주세요.', true); }
  });
  function clear() {
    game?.close(); game = null; roundData = null; deletion = null;
    if ($('give-up-dialog').open) $('give-up-dialog').close('cancel');
    if ($('delete-records-dialog').open) $('delete-records-dialog').close('cancel');
    $('guess-word').value = '';
    message('회차 데이터를 불러오면 게임을 시작할 수 있어요.'); render();
  }
  function mount(data) {
    clear(); roundData = data; game = new Game(data, { apiURL: GUESS_API_URL });
    message('첫 단어를 입력해보세요. 유사도가 높을수록 정답과 가까워요.');
    render();
  }
  clear();
  return { clear, mount };
}
