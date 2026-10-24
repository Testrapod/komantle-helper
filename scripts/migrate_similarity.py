"""기존 아카이브의 원시 유사도를 100점 단위로 한 번만 변환한다."""

import argparse
from datetime import datetime
import hashlib
from pathlib import Path

from main import SEOUL_TIME_ZONE
from scripts.collect_data import atomic_write, json_bytes, load_archive, read_round


def migrate_archive(root):
    root = Path(root)
    manifest = load_archive(root)
    corrected, records = [], []
    # 모든 입력을 검증한 후 기록한다. 중단 시에도 기존 manifest는 유효하다.
    for record in manifest['rounds']:
        data = read_round(root, record['path'])
        if data.get('similarity_scale') == 100:
            records.append(record)
            continue
        if any(abs(row['similarity']) > 1 for row in data['words'] if row['rank'] != 0):
            raise ValueError('이전 아카이브의 원시 유사도 범위를 확인할 수 없습니다.')
        data = {**data, 'similarity_scale': 100, 'words': [
            row if row['rank'] == 0 else {**row, 'similarity': row['similarity'] * 100}
            for row in data['words']
        ]}
        content = json_bytes(data)
        relative = f"rounds/{data['round']}.{hashlib.sha256(content).hexdigest()}.json"
        corrected.append((data['round'], relative, content))
        records.append({**record, 'path': relative})
    if corrected:
        for _, relative, content in corrected:
            atomic_write(root / relative, content)
        manifest.update(rounds=records, updated_at=datetime.now(SEOUL_TIME_ZONE).isoformat())
        atomic_write(root / 'manifest.json', json_bytes(manifest))
    return [number for number, _, _ in corrected]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-dir', type=Path, default=Path('.archive'))
    args = parser.parse_args()
    print('Corrected rounds:', migrate_archive(args.archive_dir))
