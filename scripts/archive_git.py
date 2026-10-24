"""data 브랜치를 별도 worktree로 읽고 fast-forward push로 보관한다."""

import argparse
from pathlib import Path
import subprocess


def git(directory, *args, check=True):
    return subprocess.run(["git", "-C", str(directory), *args], check=check,
                          capture_output=True, text=True)


def prepare(repository, destination):
    repository, destination = Path(repository).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("아카이브 작업 경로가 이미 존재합니다. 새 작업 경로를 사용하세요.")
    ref = git(repository, "ls-remote", "--exit-code", "origin", "refs/heads/data", check=False)
    if ref.returncode == 0:
        git(repository, "fetch", "origin", "refs/heads/data")
        git(repository, "worktree", "add", "--detach", str(destination), "FETCH_HEAD")
    elif ref.returncode == 2:
        git(repository, "worktree", "add", "--detach", str(destination), "HEAD")
        git(destination, "checkout", "--orphan", "archive-bootstrap")
        git(destination, "rm", "-rf", "--ignore-unmatch", ".")
    else:
        raise RuntimeError("원격 아카이브를 확인하지 못했습니다. 빈 아카이브로 초기화하지 않습니다.")


def save(destination):
    destination = Path(destination).resolve()
    allowed = {".git", "manifest.json", "operations.json", "rounds"}
    if any(path.name not in allowed for path in destination.iterdir()):
        raise ValueError("아카이브에 예상하지 않은 파일이 있습니다.")
    for name in ("manifest.json", "rounds", "operations.json"):
        if (destination / name).exists():
            git(destination, "add", "--", name)
    diff = git(destination, "diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        return False
    if diff.returncode != 1:
        raise RuntimeError("아카이브 변경을 확인하지 못했습니다.")
    git(destination, "-c", "user.name=github-actions[bot]", "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "-m", "Update Komantle data archive")
    # 원격이 변경되면 덮어쓰지 않고 실패한다. 다음 실행에서 최신 브랜치를 다시 읽는다.
    git(destination, "push", "origin", "HEAD:refs/heads/data")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "save"])
    parser.add_argument("--archive-dir", type=Path, default=Path(".archive"))
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(Path.cwd(), args.archive_dir)
    else:
        print("아카이브 저장 완료" if save(args.archive_dir) else "아카이브 변경 없음")
