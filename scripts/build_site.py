"""python -m scripts.build_site --archive-dir .archive --output dist"""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from scripts.collect_data import load_archive, read_round

ROOT = Path(__file__).resolve().parents[1]


def build_site(archive, output, *, web=ROOT / "web"):
    archive, output, web = Path(archive).resolve(), Path(output).resolve(), Path(web).resolve()
    if output == ROOT or output in (archive, web) or output in archive.parents or output in web.parents:
        raise ValueError("출력 경로가 소스나 아카이브를 덮어쓸 수 없습니다.")
    if output.exists() and not (output / ".komantle-build").is_file():
        raise ValueError("기존 출력 폴더가 이 도구로 생성한 폴더가 아닙니다.")
    manifest = load_archive(archive)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / "site"
        shutil.copytree(web, stage)
        target = stage / "data"
        (target / "rounds").mkdir(parents=True)
        # 이전 manifest를 캐시한 방문자를 위해 수정 전 파일도 보존한다.
        for path in sorted((archive / "rounds").glob("*.json")):
            read_round(archive, f"rounds/{path.name}")
            shutil.copyfile(path, target / "rounds" / path.name)
        (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False) + "\n")
        (stage / ".nojekyll").touch()
        (stage / ".komantle-build").touch()
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(stage), output)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=Path(".archive"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    manifest = build_site(args.archive_dir, args.output)
    print(f"정적 사이트 생성 완료: {args.output} ({len(manifest['rounds'])}개 회차)")
