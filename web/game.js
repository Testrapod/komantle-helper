export const GAME_PREFIX = 'komantle-helper:game:v1:';

export function normalizeGuess(value) {
  if (typeof value !== 'string') throw new Error('단어를 입력해주세요.');
  const word = value.normalize('NFC').trim().toLowerCase();
  if (!word || Array.from(word).length > 64 || /[\s\u0000-\u001f]/u.test(word)) throw new Error('공백 없이 1~64글자의 단어를 입력해주세요.');
  return word;
}

export function validateGuess(result, word, answer) {
  if (!result || result.word !== word || !Number.isFinite(result.similarity) || result.similarity < -100 || result.similarity > 100 || (result.rank !== null && (!Number.isInteger(result.rank) || result.rank < 0 || result.rank > 1000)) || typeof result.correct !== 'boolean' || result.correct !== (result.rank === 0) || result.correct !== (word === answer) || (result.correct && result.similarity !== 100)) throw new Error('채점 결과와 회차 데이터가 일치하지 않아요. 다시 불러와주세요.');
  return { word, similarity: result.similarity, rank: result.rank, correct: result.correct };
}

export class Game {
  constructor(data, { apiURL = null, storage, fetcher = globalThis.fetch } = {}) {
    this.round = data.round; this.apiURL = apiURL; this.fetcher = (...args) => fetcher.call(globalThis, ...args);
    this.words = new Map();
    for (const row of [...data.words].sort((a, b) => a.rank - b.rank)) {
      const word = normalizeGuess(row.word);
      if (!this.words.has(word)) this.words.set(word, row);
    }
    this.answer = normalizeGuess(data.words.find(row => row.rank === 0).word);
    this.guesses = []; this.givenUp = false; this.pending = false; this.closed = false; this.warning = '';
    this.key = `${GAME_PREFIX}${data.round}`;
    try { this.storage = storage === undefined ? globalThis.localStorage : storage; } catch { this.warning = '이 브라우저에서는 기록을 저장할 수 없어요.'; }
    this.restore();
  }

  get won() { return this.guesses.some(guess => guess.correct); }
  get finished() { return this.won || this.givenUp; }

  restore() {
    try {
      const text = this.storage?.getItem(this.key);
      if (!text) return;
      const data = JSON.parse(text);
      if (data.schema_version !== 1 || data.round !== this.round || typeof data.given_up !== 'boolean' || !Array.isArray(data.guesses) || data.guesses.length > 1000) throw new Error();
      const seen = new Set(), guesses = [];
      let corrected = false;
      for (const row of data.guesses) {
        const word = normalizeGuess(row.word);
        if (seen.has(word) || guesses.some(guess => guess.correct)) throw new Error();
        let guess = validateGuess(row, word, this.answer);
        const cached = this.words.get(word);
        if (cached) {
          corrected ||= guess.similarity !== cached.similarity || guess.rank !== cached.rank;
          guess = validateGuess({ word, similarity: cached.similarity, rank: cached.rank, correct: cached.rank === 0 }, word, this.answer);
        }
        guesses.push(guess); seen.add(word);
      }
      this.guesses = guesses; this.givenUp = data.given_up;
      if (corrected) this.save();
    } catch { this.warning = '이전 기록을 읽지 못해 새 게임으로 시작했어요.'; }
  }

  save() {
    try {
      if (!this.storage) throw new Error();
      this.storage.setItem(this.key, JSON.stringify({ schema_version: 1, round: this.round, given_up: this.givenUp, guesses: this.guesses }));
      this.warning = '';
    } catch { this.warning = '기록을 저장하지 못했어요. 현재 화면에서는 계속 플레이할 수 있어요.'; }
  }

  async submit(text) {
    if (this.finished || this.closed) throw new Error('이미 끝난 게임입니다. 다른 회차를 선택해주세요.');
    if (this.pending) throw new Error('이전 단어를 채점 중이에요.');
    const word = normalizeGuess(text);
    if (this.guesses.some(guess => guess.word === word)) throw new Error('이미 입력한 단어예요. 추측 횟수는 늘어나지 않아요.');
    if (this.guesses.length >= 1000) throw new Error('회차당 최대 1,000번까지 추측할 수 있어요.');
    this.pending = true;
    try {
      const row = this.words.get(word);
      let result;
      if (row) result = { word, similarity: row.similarity, rank: row.rank, correct: row.rank === 0 };
      else {
        if (!this.apiURL) throw new Error('실시간 채점 연결을 사용할 수 없어요. 잠시 후 다시 시도해주세요.');
        this.controller = new AbortController();
        const timeout = setTimeout(() => this.controller.abort(), 15000);
        try {
          const response = await this.fetcher(this.apiURL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ round: this.round, word }), signal: this.controller.signal });
          const body = await response.json();
          if (!response.ok) throw new Error(typeof body.error === 'string' ? body.error : '채점하지 못했어요. 잠시 후 다시 시도해주세요.');
          result = body;
        } catch (error) {
          if (error.name === 'AbortError' || error instanceof TypeError || error instanceof SyntaxError) throw new Error('채점 서버에 연결하지 못했어요. 잠시 후 다시 시도해주세요.');
          throw error;
        } finally { clearTimeout(timeout); }
      }
      if (this.closed) throw new Error('다른 회차로 이동했어요.');
      const guess = validateGuess(result, word, this.answer);
      this.guesses.push(guess); this.save();
      return guess;
    } finally { this.pending = false; }
  }

  giveUp() { if (!this.won) { this.givenUp = true; this.save(); } return this.answer; }
  close() { this.closed = true; this.controller?.abort(); }
}
