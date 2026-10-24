"""python -m scripts.collect_data --archive-dir .archive

회차별 실패는 결과 JSON으로 반환한다. 정상 수집분을 저장한 후 호출자가 배포 여부를 결정한다.
"""

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from main import KomantleError, Word, WordManager, SEOUL_TIME_ZONE, get_round_date, get_today_round

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


def load_archive(root, today=None):
    root = Path(root)
    path = root / "manifest.json"
    if not path.exists():
        if root.exists() and any(p.name != ".git" for p in root.iterdir()):
            raise ValueError("비어 있지 않은 아카이브에서 manifest.json을 찾을 수 없습니다.")
        return {"schema_version": 1, "timezone": "Asia/Seoul", "latest_round": None, "rounds": []}
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1 or manifest.get("timezone") != "Asia/Seoul" or not isinstance(manifest.get("rounds"), list):
        raise ValueError("아카이브 목록 형식이 올바르지 않습니다.")
    seen = []
    for row in manifest["rounds"]:
        data = read_round(root, row["path"], today)
        if row["round"] != data["round"] or row["date"] != data["date"] or row["word_count"] != 1001:
            raise ValueError("아카이브 목록과 파일이 일치하지 않습니다.")
        seen.append(data["round"])
    if seen != sorted(set(seen)) or manifest["latest_round"] != (max(seen) if seen else None):
        raise ValueError("아카이브 회차 목록이 올바르지 않습니다.")
    return manifest


def export_round(manager, number, now):
    data = {
        "schema_version": 1, "round": number, "date": get_round_date(number).isoformat(),
        "timezone": "Asia/Seoul", "collected_at": now.isoformat(),
        "source": f"https://semantle-ko.newsjel.ly/top_scores/{number}",
        "analyzer": {"name": "Okt", "konlpy_version": "0.6.0", "rules_version": 1},
        "words": [
            {"rank": entry["word_id"], "word": entry["word"].word,
             "pos": entry["word"].pos, "initial_consonant": entry["word"].initial_consonant,
             "length": entry["word"].length, "similarity": entry["similarity"]}
            for entry in sorted(manager.word_list, key=lambda entry: entry["word_id"])
        ],
    }
    return validate_round(data, get_today_round(now))


class BoundedRetry(Retry):
    def get_retry_after(self, response):
        delay = super().get_retry_after(response)
        return min(delay, 10) if delay is not None else None


def fetch_manager(number):
    # Retry-After로 무제한 대기하지 않도록 재시도와 대기 시간을 제한한다.
    retry = BoundedRetry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                         allowed_methods=["GET"], respect_retry_after_header=True)
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return WordManager(number, request_get=session.get)


def collect_archive(root, *, now=None, force_round=None, manager_factory=fetch_manager):
    now = (now or datetime.now(SEOUL_TIME_ZONE)).astimezone(SEOUL_TIME_ZONE)
    today = get_today_round(now)
    root = Path(root)
    manifest = load_archive(root, today)
    records = {row["round"]: row for row in manifest["rounds"]}
    if force_round is not None and (type(force_round) is not int or not 0 <= force_round <= today):
        raise ValueError("강제 수집 회차는 오늘 이하의 0 이상의 정수여야 합니다.")
    targets = [force_round] if force_round is not None else range(max(0, today - 2), today + 1)
    result = {"saved_rounds": [], "failed_rounds": {}, "today_available": today in records}
    for number in targets:
        if number in records and force_round is None:
            continue
        try:
            data = export_round(manager_factory(number), number, now)
        except Exception as error:
            result["failed_rounds"][str(number)] = str(error) if isinstance(error, (KomantleError, ValueError)) else "수집 또는 품사 분석 실패"
            continue
        content = json_bytes(data)
        relative = f"rounds/{number}.{hashlib.sha256(content).hexdigest()}.json"
        atomic_write(root / relative, content)
        read_round(root, relative, today)
        records[number] = {"round": number, "date": data["date"], "path": relative, "word_count": 1001}
        manifest = {"schema_version": 1, "timezone": "Asia/Seoul", "updated_at": now.isoformat(),
                    "latest_round": max(records), "rounds": sorted(records.values(), key=lambda row: row["round"])}
        atomic_write(root / "manifest.json", json_bytes(manifest))
        result["saved_rounds"].append(number)
    result["today_available"] = today in records
    return result


def archive_digest(root):
    load_archive(root)
    return hashlib.sha256((Path(root) / "manifest.json").read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=Path(".archive"))
    parser.add_argument("--force-round", type=int)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    try:
        result = collect_archive(args.archive_dir, force_round=args.force_round)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"아카이브 처리 실패: {error}\n")
    if args.result:
        atomic_write(args.result, json_bytes(result))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
