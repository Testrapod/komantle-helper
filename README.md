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
게임 아래의 **이 회차 기록 삭제** 또는 **전체 회차 기록 삭제** 버튼으로 저장된 기록을 비울 수 있습니다.
확인창에서 삭제하면 해당 범위의 추측 기록과 정답·포기 상태가 지워지고 현재 회차를 다시 시작합니다.
전체 삭제는 이 앱의 게임 기록만 지우며, 삭제한 기록은 되돌릴 수 없습니다.

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

## 꼬맨틀 헬퍼 CLI

숫자 메뉴 없이, 하나의 입력창에서 추측과 힌트를 함께 사용합니다.
단어를 입력하면 추측하고 `/`를 누르면 설명이 있는 명령 팔레트가 열립니다.

```text
 (\_/)     꼬맨틀 헬퍼
 ( •‿•)    오늘의 단어로 가는 작은 실마리
 / > <\

 › 과일
   1번째 · 과일 · 유사도 51.25 · 1위

 › /hint initial
```

### 설치와 실행

Python 3.12 이상을 사용합니다. 아카이브의 힌트·품사와 게임에는 Java가 필요하지 않습니다.

```sh
uv venv --seed --python 3.12 .venv
source .venv/bin/activate
python -m pip install -e .
komantle
```

이미 준비된 이 작업 공간에서는 `source .venv/bin/activate` 후 `komantle`을 실행하면 됩니다.
`uv`가 없다면 첫 명령을 `python3.12 -m venv .venv`로 바꿉니다.
`python -m komantle_helper`와 `python main.py`로도 실행할 수 있습니다.

```sh
komantle --round 1667
komantle --state-dir /tmp/komantle-records
komantle --no-color --no-animation
```

| 명령 | 동작 |
| --- | --- |
| `/round` · `/round today` | 회차 선택 · 오늘 회차 |
| `/rank 50` | 50위 단어의 힌트 선택, 0은 정답 |
| `/hint` | 길이·품사·초성·유사도·한 글자·전체 단어 선택 |
| `/hint char 2` | 두 번째 글자 공개 |
| `/hide` | 공개한 힌트 모두 숨기기 |
| `/history` | 유사도 순 추측 기록 |
| `/giveup` | 확인 후 정답 공개와 포기 |
| `/records delete current` · `/records delete all` | 확인 후 현재·전체 CLI 기록 삭제 |
| `/status` · `/refresh` | 데이터 상태 · 새로 불러오기 |
| `/settings` · `/help` · `/quit` | 화면 설정 · 도움말 · 종료 |

`/힌트 초성`, `/회차 오늘`, `/기록`처럼 한글 명령도 사용할 수 있습니다.
공개한 힌트는 갱신 패널에 표시하고, 회차·순위를 바꾸면 모두 숨깁니다.
전체 단어 공개와 게임 포기는 별개이며, 전체 단어·포기·삭제 확인은 취소가 기본값입니다.

CLI는 웹과 같은 공개 아카이브를 읽고 검증한 회차를 캐시합니다. 오늘 데이터가 없으면 최신
보관 회차와 갱신 대기를 표시합니다. `/round today`는 원본 조회로 오늘 회차를 시도합니다.
과거 회차의 미보관 단어는 원본 API의 채점 기간이 지나면 채점할 수 없습니다.

게임 기록과 화면 설정은 `~/.local/state/komantle-helper/`, 데이터 캐시는
`~/.cache/komantle-helper/`에 저장합니다. `--state-dir`/`KOMANTLE_STATE_DIR`,
`--cache-dir`/`XDG_CACHE_HOME`으로 위치를 바꿀 수 있습니다. 웹 브라우저와 기록을 동기화하지 않습니다.

입력·화면·오프라인 사용법은 [CLI 사용 안내](docs/cli.md)를 참고하세요.

### 데이터 수집과 원본 품사 분석

수집기 또는 원본 직접 조회의 품사 분석을 사용할 때만 추가 분석 모듈과 Java가 필요합니다.

```sh
python -m pip install -e '.[analysis]'
# 개발·수집 환경 전체 설치는 python -m pip install -r requirements.txt
```

기존 Okt 분석 규칙을 사용하며, 여러 형태소로 나뉜 단어는 `기타`로 표시될 수 있습니다.
macOS에서 Java를 찾지 못하면 `export JAVA_HOME="$(/usr/libexec/java_home)"`을 실행하세요.

### API·Java 없이 CLI 확인

```sh
python -m scripts.demo_data
komantle --archive-dir .demo-archive --state-dir /tmp/komantle-demo
```

합성 데이터이며 실제 정답이 아닙니다. 보관된 예시 단어 `과일`로 추측을 확인할 수 있습니다.
미보관 단어를 입력하면 실제 채점 API에 연결을 시도합니다.

## 테스트

```sh
# 개발 환경 설치 후 CLI·수집·누적 보관·빌드·Git 통합 테스트. 실제 API 테스트는 기본적으로 건너뜁니다.
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
