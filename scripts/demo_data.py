"""API·Java 없이 UI를 검증할 합성 데이터를 생성한다. 실제 배포에 사용하지 않는다."""

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import Word
from scripts.collect_data import collect_archive


def demo_manager(number):
    texts = ["사과", "과일", "행복", "기쁘다", "까치", "A😀가"]
    return SimpleNamespace(word_list=[
        {"word_id": rank, "word": Word(texts[rank % len(texts)]),
         "similarity": 100.0 if rank == 0 else round(60 - rank / 25, 2)}
        for rank in range(1001)
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=Path(".demo-archive"))
    args = parser.parse_args()
    with patch.object(Word, "_get_pos", return_value="명사"):
        print(collect_archive(args.archive_dir, manager_factory=demo_manager))
