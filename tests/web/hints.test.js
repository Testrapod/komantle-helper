import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRank, todayRound, hintValue } from '../../web/hints.js';
import { validateManifest, validateRound } from '../../web/data.js';

test('rank accepts only integer ranks including both endpoints', () => {
  assert.equal(parseRank('0'), 0); assert.equal(parseRank('1000'), 1000);
  for (const value of ['', '-1', '1001', '1.2', '1e2', 'abc']) assert.throws(() => parseRank(value));
});

test('today uses Korean midnight including UTC date boundary', () => {
  assert.equal(todayRound(new Date('2026-10-23T14:59:59Z')), 1666);
  assert.equal(todayRound(new Date('2026-10-23T15:00:00Z')), 1667);
  assert.equal(todayRound(new Date('2022-03-31T15:00:00Z')), 0);
});

test('character hints match Python code points and validate positions', () => {
  const word = { word: 'A😀가', length: 3, pos: '기타', initial_consonant: 'ㄱ', similarity: 42.1234 };
  assert.equal(hintValue(word, 'character', '2'), '2번째 글자 · 😀');
  assert.equal(hintValue(word, 'length'), '3글자');
  assert.equal(hintValue(word, 'similarity'), '42.12');
  for (const value of ['0', '4', '1.5', '', '-1']) assert.throws(() => hintValue(word, 'character', value));
});

test('manifest rejects traversal paths, duplicates and unsupported schemas', () => {
  const row = { round: 1667, date: '2026-10-24', path: `rounds/1667.${'a'.repeat(64)}.json`, word_count: 1001 };
  const data = { schema_version: 1, timezone: 'Asia/Seoul', latest_round: 1667, rounds: [row] };
  assert.equal(validateManifest(data), data);
  assert.throws(() => validateManifest({ ...data, schema_version: 2 }));
  assert.throws(() => validateManifest({ ...data, rounds: [row, row] }));
  assert.throws(() => validateManifest({ ...data, rounds: [{ ...row, path: '../secret.json' }] }));
});

test('round validates completeness and refuses inconsistent words', () => {
  const data = { schema_version: 1, round: 1667, date: '2026-10-24', timezone: 'Asia/Seoul', collected_at: '2026-10-24T00:07:00+09:00', words: Array.from({ length: 1001 }, (_, rank) => ({ rank, word: '사과', length: 2, pos: '명사', initial_consonant: 'ㅅㄱ', similarity: rank === 0 ? 100 : 50 })) };
  assert.equal(validateRound(data, 1667), data);
  assert.throws(() => validateRound({ ...data, words: data.words.slice(1) }, 1667));
  const copy = structuredClone(data); copy.words[1].rank = 0;
  assert.throws(() => validateRound(copy, 1667));
});
