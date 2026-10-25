"""공개 아카이브의 파일 계약과 원자적 저장."""

from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from .core import Word, get_round_date, get_today_round

POSITIONS = {"명사", "동사", "형용사", "부사", "기타"}
ROUND_PATH = re.compile(r"rounds/(\d+)\.([a-f0-9]{64})\.json")


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def validate_round(data, today=None):
    today = get_today_round() if today is None else today
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("지원하지 않는 회차 데이터입니다.")
    if "similarity_scale" in data and data["similarity_scale"] != 100:
        raise ValueError("지원하지 않는 유사도 단위입니다.")
    number = data.get("round")
    if type(number) is not int or not 0 <= number <= today:
        raise ValueError("유효하지 않거나 미래의 회차입니다.")
    if data.get("date") != get_round_date(number).isoformat() or data.get("timezone") != "Asia/Seoul":
        raise ValueError("회차와 날짜가 일치하지 않습니다.")
    stamp = datetime.fromisoformat(data["collected_at"])
    if stamp.tzinfo is None:
        raise ValueError("수집 시각에 시간대가 없습니다.")
    words = data.get("words")
    if not isinstance(words, list) or len(words) != 1001:
        raise ValueError("정답과 1~1000위 전체가 필요합니다.")
    seen = set()
    for row in words:
        if not isinstance(row, dict):
            raise ValueError("단어 데이터 형식이 올바르지 않습니다.")
        rank, text, score = row.get("rank"), row.get("word"), row.get("similarity")
        if type(rank) is not int or not 0 <= rank <= 1000 or rank in seen:
            raise ValueError("순위가 누락되었거나 중복되었습니다.")
        seen.add(rank)
        if not isinstance(text, str) or not text or row.get("pos") not in POSITIONS:
            raise ValueError("단어 또는 품사가 올바르지 않습니다.")
        word = Word(text)
        if type(row.get("length")) is not int or row["length"] != word.length or row.get("initial_consonant") != word.initial_consonant:
            raise ValueError("길이 또는 초성이 일치하지 않습니다.")
        if type(score) not in (int, float) or not math.isfinite(score) or not -100 <= score <= 100:
            raise ValueError("유사도가 올바르지 않습니다.")
        if rank == 0 and score != 100:
            raise ValueError("정답 유사도가 올바르지 않습니다.")
    return data


def read_round(root, relative, today=None):
    match = ROUND_PATH.fullmatch(relative)
    if not match:
        raise ValueError("회차 파일 경로가 올바르지 않습니다.")
    path = Path(root) / relative
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("심볼릭 링크 데이터는 지원하지 않습니다.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != match[2]:
        raise ValueError("회차 파일의 해시가 일치하지 않습니다.")
    data = validate_round(json.loads(content), today)
    if data["round"] != int(match[1]):
        raise ValueError("파일명과 회차가 일치하지 않습니다.")
    return data

