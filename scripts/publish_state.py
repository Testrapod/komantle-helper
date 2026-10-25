"""발행 여부 및 마지막 성공 배포 정보를 관리한다."""

import argparse
import json
import os
from pathlib import Path

from komantle_helper.core import get_today_round
from komantle_helper.archive import atomic_write, json_bytes
from scripts.collect_data import archive_digest, load_archive


def publication_state(root, code_sha, *, scheduled=False):
    root = Path(root)
    manifest = load_archive(root)
    digest = archive_digest(root) if manifest["rounds"] else ""
    state_file = root / "operations.json"
    previous = json.loads(state_file.read_text()) if state_file.exists() else {}
    today_available = any(row["round"] == get_today_round() for row in manifest["rounds"])
    unchanged = previous.get("code_sha") == code_sha and previous.get("data_digest") == digest
    return {"deploy": bool(manifest["rounds"]) and not unchanged and (not scheduled or today_available),
            "today_available": today_available, "data_digest": digest,
            "round_count": len(manifest["rounds"]), "latest_round": manifest["latest_round"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=Path(".archive"))
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--record-success", action="store_true")
    args = parser.parse_args()
    state = publication_state(args.archive_dir, args.code_sha, scheduled=args.scheduled)
    if args.record_success:
        if not state["data_digest"]:
            parser.error("빈 아카이브에는 배포 성공을 기록할 수 없습니다.")
        atomic_write(args.archive_dir / "operations.json", json_bytes({"code_sha": args.code_sha, "data_digest": state["data_digest"]}))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            for key, value in state.items():
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(f"### 꼬맨틀 발행 결과\n\n코드: `{args.code_sha}`\n\n")
            stream.write(f"보관: {state['round_count']}개 회차 / 최신 {state['latest_round']}회\n\n")
            stream.write(f"오늘 데이터: {state['today_available']} / 배포 필요: {state['deploy']}\n\n")
            result_file = Path("collection-result.json")
            if result_file.exists():
                result = json.loads(result_file.read_text())
                stream.write(f"수집 성공: {result['saved_rounds']} / 실패 회차: {list(result['failed_rounds'])}\n")
    print(json.dumps(state, ensure_ascii=False))
