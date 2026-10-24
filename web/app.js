import { loadManifest, loadRound } from './data.js';
import { LABELS, parseRank, todayRound, hintValue } from './hints.js';

const $ = id => document.getElementById(id);
const buttons = [...document.querySelectorAll('[data-hint]')];
const manifestURL = new URL('./data/manifest.json', document.baseURI);
let manifest, roundData, words, selectedWord, controller;
let requestId = 0;
let seenToday = todayRound();
const revealed = new Set();

function closeHint(kind) {
  revealed.delete(kind);
  const button = buttons.find(button => button.dataset.hint === kind);
  $(`value-${kind}`).textContent = '아직 열지 않은 힌트';
  button.setAttribute('aria-expanded', 'false');
  button.closest('article').classList.remove('is-open');
  button.replaceChildren(document.createTextNode(`${LABELS[kind]} 보기 `));
  const icon = document.createElement('span'); icon.setAttribute('aria-hidden', 'true'); icon.textContent = kind === 'word' ? '↗' : '+'; button.append(icon);
}

function reset() {
  for (const kind of Object.keys(LABELS)) closeHint(kind);
  if ($('answer-dialog').open) $('answer-dialog').close('cancel');
}

function setReady(ready) {
  for (const button of buttons) button.disabled = !ready;
  $('reset').disabled = !ready;
  $('character').disabled = !ready;
  $('hint-grid').setAttribute('aria-busy', String(!ready));
}

function setError(message) {
  $('error-message').textContent = message;
  $('load-error').hidden = !message;
}

function selectRank() {
  reset(); selectedWord = null;
  $('rank-error').hidden = true;
  $('rank').removeAttribute('aria-invalid');
  try {
    const rank = parseRank($('rank').value);
    selectedWord = words?.get(rank);
    $('target').textContent = selectedWord ? `${roundData.round}회 · ${rank === 0 ? '정답' : `${rank}위 단어`}` : '데이터를 불러오는 중';
  } catch (error) {
    $('rank-error').textContent = error.message;
    $('rank-error').hidden = false;
    $('rank').setAttribute('aria-invalid', 'true');
    $('target').textContent = '순위를 확인해주세요';
  }
  setReady(Boolean(selectedWord));
}

function updateNotice() {
  const latest = manifest?.rounds.at(-1);
  const today = todayRound();
  const messages = [];
  if (latest && latest.round < today) messages.push(`오늘 회차는 갱신 대기 중이에요. 현재 ${roundData?.date || latest.date} 회차를 보고 있어요.`);
  if (!latest) messages.push('아직 보관된 회차가 없어요. 데이터가 준비되면 다시 불러와주세요.');
  $('notice').textContent = messages.join(' ');
  $('notice').hidden = !messages.length;
}

async function chooseRound(number, retry = true) {
  const id = ++requestId;
  controller?.abort(); controller = new AbortController();
  reset(); setReady(false); setError(''); words = null; selectedWord = null; roundData = null;
  $('target').textContent = '데이터를 불러오는 중';
  $('data-date').textContent = '회차 데이터 확인 중'; $('collected-at').textContent = '잠시만 기다려주세요.';
  try {
    const record = manifest.rounds.find(row => row.round === number);
    if (!record) throw new Error('보관되지 않은 회차예요. 다른 회차를 선택해주세요.');
    const data = await loadRound(manifestURL, record, controller.signal);
    if (id !== requestId) return;
    roundData = data; words = new Map(data.words.map(word => [word.rank, word]));
    $('character').value = '1';
    $('data-date').textContent = `${data.date} · ${data.round}회 데이터`;
    $('collected-at').textContent = `수집 ${new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(data.collected_at))} (한국 시간)`;
    selectRank(); updateNotice();
  } catch (error) {
    if (id !== requestId || error.name === 'AbortError') return;
    if (retry) {
      try {
        manifest = await loadManifest(manifestURL, controller.signal);
        if (id !== requestId) return;
        if (manifest.rounds.some(row => row.round === number)) return chooseRound(number, false);
      } catch { /* 원래 오류를 사용자에게 표시한다. */ }
    }
    $('target').textContent = '데이터를 불러오지 못했어요'; $('data-date').textContent = '연결을 확인해주세요'; $('collected-at').textContent = '';
    setError(error.message); updateNotice();
  }
}

async function start(preferred = $('round').disabled ? NaN : Number($('round').value)) {
  const id = ++requestId;
  controller?.abort(); controller = new AbortController();
  reset(); setReady(false); setError(''); words = null; selectedWord = null; roundData = null; $('round').disabled = true;
  try {
    manifest = await loadManifest(manifestURL, controller.signal);
    if (id !== requestId) return;
    // 미래 회차는 목록에 넣지 않는다. 브라우저의 한국 날짜가 기준이다.
    manifest = { ...manifest, rounds: manifest.rounds.filter(row => row.round <= todayRound()) };
    $('round').replaceChildren();
    for (const row of [...manifest.rounds].reverse()) {
      const option = document.createElement('option'); option.value = row.round; option.textContent = `${row.date} · ${row.round}회`; $('round').append(option);
    }
    updateNotice();
    if (!manifest.rounds.length) {
      $('target').textContent = '보관된 회차가 없어요'; $('data-date').textContent = '데이터 준비 중'; $('collected-at').textContent = '';
      const option = document.createElement('option'); option.textContent = '아직 보관된 회차가 없어요'; $('round').append(option);
      setError('아직 데이터가 준비되지 않았어요. 잠시 후 다시 불러와주세요.');
      return;
    }
    $('round').disabled = false;
    const number = manifest.rounds.some(row => row.round === preferred) ? preferred : manifest.rounds.at(-1).round;
    $('round').value = number;
    await chooseRound(number);
  } catch (error) {
    if (id !== requestId || error.name === 'AbortError') return;
    $('target').textContent = '데이터를 불러오지 못했어요'; $('data-date').textContent = '연결을 확인해주세요'; $('collected-at').textContent = '';
    setError('데이터 목록을 불러오지 못했어요. 연결을 확인하고 다시 시도해주세요.');
  }
}

function reveal(kind) {
  if (!selectedWord) return;
  try {
    const value = hintValue(selectedWord, kind, $('character').value);
    $(`value-${kind}`).textContent = value;
    const button = buttons.find(button => button.dataset.hint === kind);
    button.textContent = '다시 숨기기 −'; button.setAttribute('aria-expanded', 'true'); button.closest('article').classList.add('is-open');
    revealed.add(kind);
  } catch (error) { $(`value-${kind}`).textContent = error.message; }
}

for (const button of buttons) button.addEventListener('click', () => {
  const kind = button.dataset.hint;
  if (revealed.has(kind)) return closeHint(kind);
  if (kind === 'word') return $('answer-dialog').showModal();
  reveal(kind);
});
$('answer-dialog').addEventListener('close', () => { if ($('answer-dialog').returnValue === 'reveal') reveal('word'); });
$('reset').addEventListener('click', reset);
$('round').addEventListener('change', () => chooseRound(Number($('round').value)));
$('rank').addEventListener('input', selectRank);
$('character').addEventListener('input', () => closeHint('character'));
$('retry').addEventListener('click', () => start());
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && seenToday !== todayRound()) { seenToday = todayRound(); start(); }
});
start();
