# 꼬맨틀 헬퍼
[꼬맨틀](https://semantle-ko.newsjel.ly/)을 더 재미있게(?) 즐길 수 있도록 여러가지 도움을 주는 프로그램 입니다.

순위 0(정답) ~ 1000의 단어, 품사, 초성, 글자 수, 유사도를 조회합니다.
터미널 프로그램과 GitHub Pages용 정적 웹 버전을 제공합니다.

## 웹 버전

[꼬맨틀 헬퍼 웹사이트 바로가기](https://testrapod.github.io/komantle-helper/)

웹에서는 회차와 순위를 선택한 뒤 길이·품사·초성·유사도·한 글자·전체 단어를 개별 공개합니다.
회차 또는 순위를 바꾸면 공개 상태가 초기화되며, 전체 단어는 확인창을 거쳐 공개합니다.

같은 화면에서 단어를 입력해 직접 게임을 진행할 수 있습니다. 추측 기록은 유사도 순으로 표시하며,
정답 판정·중복 입력 방지·포기·새로고침 후 이어하기를 지원합니다.
기록은 브라우저의 localStorage에 회차별로 저장되고 원본 사이트나 CLI 기록과 동기화하지 않습니다.

보관된 단어는 JSON의 점수를 사용하고, 그 밖의 단어는 별도 채점 API를 통해 원본 점수를 조회합니다.
원본의 조회 기간이 지난 회차에서 보관되지 않은 단어는 채점할 수 없으며, 실패한 추측은 횟수에 포함하지 않습니다.
채점 API는 공용 [API 서비스](https://api.eastsea-y.chatgpt.site)의 `POST /api/komantle-helper/v1/guess`를 사용합니다.
서버 소스와 서버 단위 테스트는 `chatgpt-sites` 저장소의 `sites/api/`에서 관리하고,
이 저장소에서는 웹 클라이언트와 API 응답 처리·브라우저 테스트를 관리합니다.
API는 `{round, word}`를 받아 `{word, similarity, rank, correct}`를 반환하며, 오류는 `{error}` 문자열과 HTTP 상태로 전달합니다.

원본 `top_scores`와 `guess` API의 유사도는 -1~1이며, 수집·채점 경계에서 ×100하여
화면·보관 JSON·게임 기록을 모두 -100~100 단위로 통일합니다.
기존 아카이브는 배포 시 `python -m scripts.migrate_similarity`로 한 번 변환합니다.
변환된 JSON은 `similarity_scale: 100`으로 구분하고, 이전 파일은 보존합니다.
웹·CLI의 기존 추측 기록은 회차 데이터를 기준으로 점수를 정정하며 시도 횟수와 게임 상태를 유지합니다.

데이터는 GitHub Actions의 Python·Java 환경에서 생성하고 별도 `data` 브랜치에 누적 보관합니다.
GitHub Pages는 웹 자원과 보관 JSON을 함께 제공합니다. 방문자는 Python이나 Java를 설치할 필요가 없습니다.
정답을 화면에서 숨겨도 JSON에는 포함됩니다. 품사는 기존 Okt 자동 분석 규칙을 사용합니다.

### 로컬에서 실제 데이터로 실행

아래 명령은 Python 실행 환경을 준비한 후 저장소 루트에서 실행합니다.

```sh
source .venv/bin/activate
python -m scripts.collect_data --archive-dir .archive
python -m scripts.migrate_similarity --archive-dir .archive
python -m scripts.build_site --archive-dir .archive --output dist
python3 -m http.server 4173 --bind 127.0.0.1 --directory dist
```

브라우저에서 <http://127.0.0.1:4173/>를 엽니다. 첫 수집에는 인터넷과 Java가 필요합니다.
기존 정상 회차는 다시 수집하지 않으며, 수정하려면 `--force-round 1667`처럼 명시합니다.
수집 결과의 `failed_rounds`와 `today_available`도 확인하세요. 회차별 실패가 있어도 성공한 데이터는 보존합니다.

### API·Java 없이 화면 확인

```sh
python -m scripts.demo_data
python -m scripts.build_site --archive-dir .demo-archive --output .preview/komantle-helper
python3 -m http.server 4173 --bind 127.0.0.1 --directory .preview
```

<http://127.0.0.1:4173/komantle-helper/>에서 합성 예시 데이터를 확인할 수 있습니다.
`.demo-archive`는 UI 검증용이며 실제 배포에 사용하지 않습니다.
합성 데이터에 없는 단어를 입력하면 실제 채점 API를 사용하려 하므로, 완전히 오프라인으로
확인하려면 예시 단어 `과일`을 사용하거나 브라우저 테스트의 모의 응답을 사용하세요.

### GitHub Pages 운영

저장소의 Pages Source를 **GitHub Actions**로 설정하고, `main`에 워크플로가 반영된 뒤
**Collect data and publish Pages**를 수동 실행하면 첫 수집과 배포가 진행됩니다.
이후 매일 00:07 및 01:07 한국 시간에 누락 데이터를 수집하고 필요한 경우 배포합니다.
예약은 지연될 수 있으며, 오늘 데이터가 없으면 사이트에 갱신 대기를 표시합니다.

설정·권한·장애 복구는 [웹 배포 운영 안내](docs/github-pages-operations.md)를 참고하세요.

## 실행 환경

- Python 3.12 (검증 버전: 3.12.13)
- 품사 분석용 Java: macOS arm64의 JBR 21.0.11에서 검증
- 인터넷 연결: 꼬맨틀 API 조회에 필요

품사를 조회할 때만 Java를 시작합니다. 다른 힌트는 Java 없이 사용할 수 있습니다.
품사 분석은 기존 Okt 규칙을 유지합니다. 한 단어가 여러 형태소로 나뉘면 `기타`로 표시될 수 있습니다.

## 가상환경 설치와 실행

이 작업 공간에는 `.venv`가 설치되어 있습니다. 바로 실행하려면:

```sh
source .venv/bin/activate
python main.py
```

게임으로 바로 시작하려면:

```sh
python main.py --play
python main.py --play --round 1667
python main.py --play --state-dir /tmp/komantle-game-records
```

기존 힌트 메뉴의 `G`로도 게임에 들어갈 수 있습니다. 게임 중에는 `/기록`, `/포기`, `/돌아가기`를
사용합니다. CLI 기록의 기본 경로는 `~/.local/state/komantle-helper/game-<회차>.json`이며
`--state-dir` 또는 `KOMANTLE_STATE_DIR`로 변경할 수 있습니다. 게임 채점에는 Java가 필요하지 않습니다.

다른 환경에서 새로 설치하려면 (`uv` 필요):

```sh
uv venv --seed --python 3.12 .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

`uv`가 없다면 Python 3.12 설치 후 첫 명령을 `python3.12 -m venv .venv`로 대체할 수 있습니다.
macOS에서 Java를 찾지 못하면 `export JAVA_HOME="$(/usr/libexec/java_home)"`을 실행하세요.

API는 조회 가능한 회차에 제한이 있습니다. 2026-10-24 확인 시 서버는 그저께부터 내일까지의
회차만 허용하며, 오래된 회차는 HTTP 422와 함께 제한 사유를 반환했습니다.

## 테스트

```sh
# CLI·수집·누적 보관·빌드·Git 통합 테스트. 실제 API 테스트는 기본적으로 건너뜁니다.
python -m unittest discover -s tests -v

# 실제 API와 Java로 오늘 1,001개 단어의 모든 힌트 및 어제 회차 검증
KOMANTLE_LIVE_TEST=1 python -m unittest discover -s tests -v

python -m pip check

# 웹 단위 및 실제 브라우저 테스트 (Node.js 24 사용)
npm ci
npm test
npx playwright install chromium
python -m scripts.demo_data
python -m scripts.build_site --archive-dir .demo-archive --output .preview/komantle-helper
npm run test:e2e
```

2026-10-24 기준 기존 버전과 수정 버전의 실제 CLI 동작을 확인했습니다.
수정 사항과 웹사이트 전환 검토는 [검증 및 GitHub Pages 전환 보고서](docs/github-pages-review.md)에 정리했습니다.
구조, 데이터 보관, 웹 기능, 자동 배포와 단계별 완료 기준은 [GitHub Pages 웹 버전 구현 계획](docs/github-pages-plan.md)에 정리했습니다.
