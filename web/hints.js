export const LABELS = { length: '길이', pos: '품사', initial_consonant: '초성', similarity: '유사도', character: '한 글자', word: '전체 단어' };

export function parseRank(value) {
  const text = String(value).trim();
  if (!/^\d+$/.test(text) || Number(text) > 1000) throw new Error('순위는 0~1000 사이의 정수로 입력해주세요.');
  return Number(text);
}

export function todayRound(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return Math.round((Date.UTC(+values.year, +values.month - 1, +values.day) - Date.UTC(2022, 3, 1)) / 86400000);
}

export function hintValue(word, kind, position = '1') {
  switch (kind) {
    case 'length': return `${word.length}글자`;
    case 'pos': return word.pos;
    case 'initial_consonant': return word.initial_consonant || '완성형 한글 초성 없음';
    case 'similarity': return word.similarity.toFixed(2);
    case 'word': return word.word;
    case 'character': {
      const chars = Array.from(word.word);
      if (!/^\d+$/.test(String(position)) || +position < 1 || +position > chars.length) throw new Error(`위치는 1~${chars.length} 사이로 입력해주세요.`);
      return `${position}번째 글자 · ${chars[+position - 1]}`;
    }
    default: throw new Error('지원하지 않는 힌트입니다.');
  }
}
