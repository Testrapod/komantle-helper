import test from 'node:test';
import assert from 'node:assert/strict';
import { Game, GAME_PREFIX, normalizeGuess, deleteGameRecords } from '../../web/game.js';

const data = { round: 1667, words: [
  { rank: 0, word: '사과', similarity: 100 }, { rank: 1, word: '과일', similarity: 51.25 },
] };
const storage = () => { const map = new Map(); return {
  get length() { return map.size; }, key: index => [...map.keys()][index] ?? null,
  getItem: key => map.get(key), setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key),
}; };

test('deleting records targets one round or all game records while preserving other storage', () => {
  const saved = storage();
  for (const round of [1665, 1666, 1667]) new Game({ ...data, round }, { storage: saved }).giveUp();
  saved.setItem('other-app:preference', 'keep');
  deleteGameRecords(1667, saved);
  assert.equal(saved.getItem(`${GAME_PREFIX}1667`), undefined);
  assert.equal(new Game(data, { storage: saved }).givenUp, false);
  assert.equal(new Game({ ...data, round: 1666 }, { storage: saved }).givenUp, true);
  deleteGameRecords(null, saved);
  assert.equal(saved.length, 1);
  assert.equal(saved.getItem('other-app:preference'), 'keep');
});

test('storage deletion failures are reported to the caller', () => {
  assert.throws(() => deleteGameRecords(1667, { removeItem() { throw new Error('denied'); } }), /denied/);
});

test('cached guesses, duplicates, win and per-round restore', async () => {
  const saved = storage();
  const game = new Game(data, { storage: saved, fetcher: () => assert.fail('cache must not call API') });
  await game.submit(' 과일 ');
  await assert.rejects(game.submit('과일'), /이미 입력/);
  assert.equal(game.guesses.length, 1);
  await game.submit('사과');
  assert.equal(game.won, true);
  assert.equal(new Game(data, { storage: saved }).won, true);
  assert.equal(new Game({ ...data, round: 1666 }, { storage: saved }).guesses.length, 0);
  await assert.rejects(game.submit('바다'), /끝난 게임/);
});

test('uncached scoring and errors preserve attempt count', async () => {
  let calls = 0;
  const game = new Game(data, { apiURL: 'https://example.test/api/komantle-helper/v1/guess', storage: storage(), fetcher: async (url, options) => {
    calls++; assert.equal(JSON.parse(options.body).word, '바다');
    return Response.json({ word: '바다', similarity: 8, rank: null, correct: false });
  } });
  await game.submit('바다'); assert.equal(calls, 1);
  game.fetcher = async () => Response.json({ error: '모르는 단어' }, { status: 404 });
  await assert.rejects(game.submit('없는단어'), /모르는 단어/);
  assert.equal(game.guesses.length, 1);
});

test('restoring fixes cached scores without rescaling valid low live scores or losing attempts', () => {
  const saved = storage();
  saved.setItem(`${GAME_PREFIX}1667`, JSON.stringify({ schema_version: 1, round: 1667, given_up: true, guesses: [
    { word: '과일', similarity: .5125, rank: 1, correct: false },
    { word: '바다', similarity: .25, rank: null, correct: false },
  ] }));
  const game = new Game(data, { storage: saved });
  assert.deepEqual(game.guesses.map(guess => guess.similarity), [51.25, .25]);
  assert.equal(game.givenUp, true);
  assert.equal(game.guesses.length, 2);
  assert.equal(JSON.parse(saved.getItem(game.key)).guesses[0].similarity, 51.25);
  assert.deepEqual(new Game(data, { storage: saved }).guesses, game.guesses);
});

test('giveup, broken storage and quota failure remain usable', async () => {
  const saved = storage();
  const game = new Game(data, { storage: saved }); game.giveUp();
  assert.equal(new Game(data, { storage: saved }).givenUp, true);
  const broken = new Game(data, { storage: { getItem: () => '{', setItem: () => { throw Error(); } } });
  assert.ok(broken.warning); await broken.submit('과일'); assert.equal(broken.guesses.length, 1); assert.ok(broken.warning);
  for (const word of ['', '여러 단어', 'a'.repeat(65)]) assert.throws(() => normalizeGuess(word));
});

test('closed round drops late scoring response', async () => {
  let finish;
  const game = new Game(data, { apiURL: 'https://example.test/', storage: storage(), fetcher: () => new Promise(resolve => { finish = resolve; }) });
  const pending = game.submit('바다'); game.close();
  finish(Response.json({ word: '바다', similarity: 8, rank: null, correct: false }));
  await assert.rejects(pending, /다른 회차/); assert.equal(game.guesses.length, 0);
});
