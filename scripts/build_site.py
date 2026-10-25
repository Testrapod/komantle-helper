"""python -m scripts.build_site --archive-dir .archive --output dist"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from komantle_helper.archive import read_round
from scripts.collect_data import load_archive

ROOT = Path(__file__).resolve().parents[1]


def version_assets(stage):
    assets = sorted(path for path in stage.rglob('*') if path.suffix in {'.js', '.css'})
    digest = hashlib.sha256()
    for path in assets:
        digest.update(path.relative_to(stage).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    version = digest.hexdigest()[:16]
    # HTML뿐 아니라 하위 모듈도 새 URL로 요청해 배포 전 파일과 섞이지 않게 한다.
    for path in assets:
        if path.suffix == '.js':
            source = re.sub(r'''(\bfrom\s+['"])(\./[^'"]+\.js)(['"])''',
                            rf'\g<1>\g<2>?v={version}\g<3>', path.read_text())
            path.write_text(source)
    index = stage / 'index.html'
    index.write_text(re.sub(r'''((?:src|href)=['"])(\./[^'"?]+\.(?:js|css))(['"])''',
                            rf'\g<1>\g<2>?v={version}\g<3>', index.read_text()))


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
        version_assets(stage)
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
