import test from 'node:test';
import assert from 'node:assert/strict';
import { Game, normalizeGuess } from '../../web/game.js';
import { handleGuess, parseScore } from '../../backend/handler.js';

const data = { round: 1667, words: [
  { rank: 0, word: '사과', similarity: 100 }, { rank: 1, word: '과일', similarity: 51.25 },
] };
const storage = () => { const map = new Map(); return { getItem: key => map.get(key), setItem: (key, value) => map.set(key, value) }; };

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
  const game = new Game(data, { apiURL: 'https://example.test/api/guess', storage: storage(), fetcher: async (url, options) => {
    calls++; assert.equal(JSON.parse(options.body).word, '바다');
    return Response.json({ word: '바다', similarity: 8, rank: null, correct: false });
  } });
  await game.submit('바다'); assert.equal(calls, 1);
  game.fetcher = async () => Response.json({ error: '모르는 단어' }, { status: 404 });
  await assert.rejects(game.submit('없는단어'), /모르는 단어/);
  assert.equal(game.guesses.length, 1);
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

function request(input = { round: 1667, word: '바다' }, origin = 'https://testrapod.github.io') {
  return new Request('https://api.example/api/guess', { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(input) });
}
const now = new Date('2026-10-24T01:00:00Z');

test('proxy uses only the fixed upstream endpoint and returns CORS score', async () => {
  const response = await handleGuess(request(), { now, fetcher: async url => {
    assert.equal(url, 'https://semantle-ko.newsjel.ly/guess/1667/%EB%B0%94%EB%8B%A4');
    return Response.json({ guess: '바다', sim: .125, rank: '1000위 이상' });
  } });
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'https://testrapod.github.io');
  assert.deepEqual(await response.json(), { word: '바다', similarity: 12.5, rank: null, correct: false });
});

test('proxy refuses bad origins, future/old rounds and unknown words', async () => {
  const fail = () => assert.fail('invalid request must not reach upstream');
  assert.equal((await handleGuess(request(undefined, 'https://evil.test'), { now, fetcher: fail })).status, 403);
  assert.equal((await handleGuess(request({ round: 1668, word: '사과' }), { now, fetcher: fail })).status, 400);
  assert.equal((await handleGuess(request({ round: 1, word: '사과' }), { now, fetcher: fail })).status, 422);
  assert.equal((await handleGuess(request(), { now, fetcher: async () => Response.json({}, { status: 404 }) })).status, 404);
  assert.throws(() => parseScore({ guess: '사과', sim: .5, rank: true }, '사과'));
});

test('proxy handles preflight and upstream outages', async () => {
  const preflight = new Request('https://api.example/api/guess', { method: 'OPTIONS', headers: { Origin: 'https://testrapod.github.io' } });
  assert.equal((await handleGuess(preflight)).status, 204);
  const response = await handleGuess(request(), { now, fetcher: async () => { throw Error('timeout'); } });
  assert.equal(response.status, 502);
});

test('proxy cache errors do not turn successful scoring into a failure', async () => {
  const response = await handleGuess(request(), { now, cache: { match: async () => { throw Error('cache offline'); }, put: async () => { throw Error('cache offline'); } }, fetcher: async () => Response.json({ guess: '바다', sim: .1, rank: '1000위 이상' }) });
  assert.equal(response.status, 200);
  assert.equal((await response.json()).similarity, 10);
});
