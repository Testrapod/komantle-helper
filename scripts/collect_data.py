"""python -m scripts.collect_data --archive-dir .archive

회차별 실패는 결과 JSON으로 반환한다. 정상 수집분을 저장한 후 호출자가 배포 여부를 결정한다.
"""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from komantle_helper.core import KomantleError, SEOUL_TIME_ZONE, get_round_date, get_today_round
from komantle_helper.data import fetch_round
from komantle_helper.archive import atomic_write, json_bytes, read_round, validate_round


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
        "schema_version": 1, "similarity_scale": 100, "round": number, "date": get_round_date(number).isoformat(),
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
        return fetch_round(number, request_get=session.get)


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
