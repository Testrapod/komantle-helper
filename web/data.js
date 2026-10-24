const POS = new Set(['명사', '동사', '형용사', '부사', '기타']);
const START = Date.UTC(2022, 3, 1);
const roundDate = number => new Date(START + number * 86400000).toISOString().slice(0, 10);

async function getJSON(url, signal) {
  const response = await fetch(url, { cache: 'no-cache', signal });
  if (!response.ok) throw new Error('데이터를 불러오지 못했어요. 잠시 후 다시 시도해주세요.');
  return response.json();
}

export function validateManifest(data) {
  if (data?.schema_version !== 1 || data.timezone !== 'Asia/Seoul' || !Array.isArray(data.rounds)) throw new Error('지원하지 않는 데이터 목록이에요.');
  let previous = -1;
  for (const row of data.rounds) {
    if (!Number.isSafeInteger(row.round) || row.round <= previous || row.date !== roundDate(row.round) || row.word_count !== 1001 || !new RegExp(`^rounds/${row.round}\\.[a-f0-9]{64}\\.json$`).test(row.path)) throw new Error('회차 목록 형식이 올바르지 않아요.');
    previous = row.round;
  }
  if (data.latest_round !== (data.rounds.length ? previous : null)) throw new Error('최신 회차 정보가 일치하지 않아요.');
  return data;
}

export function validateRound(data, number) {
  if (data?.schema_version !== 1 || data.round !== number || data.date !== roundDate(number) || data.timezone !== 'Asia/Seoul' || !Array.isArray(data.words) || data.words.length !== 1001 || !Number.isFinite(Date.parse(data.collected_at))) throw new Error('회차 데이터 형식이 올바르지 않아요.');
  const legacy = data.similarity_scale === undefined;
  if (!legacy && data.similarity_scale !== 100) throw new Error('유사도 단위가 올바르지 않아요.');
  const ranks = new Set();
  for (const row of data.words) {
    if (!Number.isInteger(row.rank) || row.rank < 0 || row.rank > 1000 || ranks.has(row.rank) || typeof row.word !== 'string' || !row.word || !POS.has(row.pos) || typeof row.initial_consonant !== 'string' || row.length !== Array.from(row.word).length || !Number.isFinite(row.similarity) || row.similarity < -100 || row.similarity > 100 || (row.rank === 0 && row.similarity !== 100)) throw new Error('단어 데이터가 완전하지 않아요.');
    ranks.add(row.rank);
    if (legacy && row.rank !== 0 && Math.abs(row.similarity) > 1) throw new Error('이전 유사도 단위가 올바르지 않아요.');
  }
  // 이전 manifest를 캐시한 브라우저도 원시 점수를 100점 단위로 읽는다.
  return legacy ? { ...data, similarity_scale: 100, words: data.words.map(row => row.rank === 0 ? row : { ...row, similarity: row.similarity * 100 }) } : data;
}

export async function loadManifest(url, signal) {
  return validateManifest(await getJSON(url, signal));
}

export async function loadRound(manifestURL, record, signal) {
  const url = new URL(record.path, manifestURL);
  return validateRound(await getJSON(url, signal), record.round);
}
