// GitHub Pages의 게임 UI가 호출하는 고정 목적 채점 API. 임의 URL은 중계하지 않는다.
const ORIGINS = new Set(['https://testrapod.github.io']);
const START = Date.UTC(2022, 3, 1);

export function normalizeWord(value) {
  if (typeof value !== 'string') throw new Error('단어를 입력해주세요.');
  const word = value.normalize('NFC').trim().toLowerCase();
  if (!word || Array.from(word).length > 64 || /[\s\u0000-\u001f]/u.test(word)) throw new Error('공백 없이 1~64글자의 단어를 입력해주세요.');
  return word;
}

export function parseScore(data, word) {
  if (!data || data.guess !== word || !Number.isFinite(data.sim) || data.sim < -1 || data.sim > 1) throw new Error('채점 서버의 응답 형식이 올바르지 않습니다.');
  let rank;
  if (data.rank === '정답!' && data.sim === 1) rank = 0;
  else if (Number.isInteger(data.rank) && data.rank >= 1 && data.rank <= 1000) rank = data.rank;
  else if (data.rank === '1000위 이상') rank = null;
  else throw new Error('채점 서버의 순위 형식이 올바르지 않습니다.');
  return { word, similarity: data.sim * 100, rank, correct: rank === 0 };
}

export async function handleGuess(request, { fetcher = (...args) => globalThis.fetch(...args), now = new Date(), cache = null } = {}) {
  const origin = request.headers.get('Origin');
  const headers = { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', Vary: 'Origin' };
  if (ORIGINS.has(origin)) headers['Access-Control-Allow-Origin'] = origin;
  const reply = (data, status = 200) => Response.json(data, { status, headers });
  if (origin && !ORIGINS.has(origin)) return reply({ error: '허용되지 않은 출처입니다.' }, 403);
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: { ...headers, 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '86400' } });
  if (request.method !== 'POST') return reply({ error: 'POST 요청만 지원합니다.' }, 405);
  let round, word;
  try {
    if (!request.headers.get('Content-Type')?.startsWith('application/json')) return reply({ error: 'JSON 요청이 필요합니다.' }, 415);
    if (Number(request.headers.get('Content-Length')) > 4096) return reply({ error: '요청이 너무 큽니다.' }, 413);
    const text = await request.text();
    if (text.length > 1024) return reply({ error: '요청이 너무 큽니다.' }, 413);
    const input = JSON.parse(text);
    round = input.round; word = normalizeWord(input.word);
    const today = Math.floor((now.getTime() + 9 * 3600000 - START) / 86400000);
    if (!Number.isSafeInteger(round) || round < 0 || round > today) throw new Error('오늘 이하의 유효한 회차를 선택해주세요.');
    if (round < today - 2) return reply({ error: '이 회차의 실시간 채점 기간이 지났어요. 보관된 단어의 점수는 계속 확인할 수 있어요.' }, 422);
  } catch (error) { return reply({ error: error instanceof SyntaxError ? 'JSON 요청이 올바르지 않습니다.' : error.message }, 400); }
  const upstreamURL = `https://semantle-ko.newsjel.ly/guess/${round}/${encodeURIComponent(word)}`;
  const cacheKey = new Request(upstreamURL);
  let stage = 'cache-read';
  try {
    try {
      const cached = cache ? await cache.match(cacheKey) : null;
      if (cached) return reply(await cached.json());
    } catch { /* 캐시 장애는 실시간 채점을 막지 않는다. */ }
    stage = 'upstream-fetch';
    const response = await fetcher(upstreamURL, { signal: AbortSignal.timeout(10000), headers: { Accept: 'application/json' } });
    if (response.status === 404) return reply({ error: '원본 사전에 없는 단어예요. 다른 단어를 입력해주세요.' }, 404);
    if (response.status === 422) return reply({ error: '원본에서 이 회차를 채점할 수 없어요. 보관된 단어의 점수는 계속 확인할 수 있어요.' }, 422);
    if (response.status === 429) return reply({ error: '채점 요청이 많아요. 잠시 후 다시 시도해주세요.' }, 429);
    if (!response.ok) return reply({ error: '원본 채점 서버가 응답하지 않아요. 잠시 후 다시 시도해주세요.' }, 502);
    stage = 'upstream-parse';
    const result = parseScore(await response.json(), word);
    try { if (cache) await cache.put(cacheKey, Response.json(result, { headers: { 'Cache-Control': 'public, max-age=86400' } })); }
    catch { /* 정상 채점 결과는 캐시 저장 실패와 무관하게 반환한다. */ }
    return reply(result);
  } catch (error) {
    console.error('Scoring unavailable', stage, error?.name, String(error?.message || '').replace(/https?:\/\/\S+/g, '[upstream]'));
    return reply({ error: '채점 서버에 연결하지 못했어요. 잠시 후 다시 시도해주세요.' }, 502);
  }
}
