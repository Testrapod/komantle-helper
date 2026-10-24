# 꼬맨틀 헬퍼
[꼬맨틀](https://semantle-ko.newsjel.ly/)을 더 재미있게(?) 즐길 수 있도록 여러가지 도움을 주는 프로그램 입니다.

순위 0(정답) ~ 1000의 단어, 품사, 초성, 글자 수, 유사도를 조회합니다.
현재는 터미널 프로그램이며 GitHub Pages 웹 버전은 아직 구현하지 않았습니다.

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
# 오프라인 회귀 테스트 22개. 실제 API 테스트 1개는 기본적으로 건너뜁니다.
python -m unittest discover -s tests -v

# 실제 API와 Java로 오늘 1,001개 단어의 모든 힌트 및 어제 회차 검증
KOMANTLE_LIVE_TEST=1 python -m unittest discover -s tests -v

python -m pip check
```

2026-10-24 기준 기존 버전과 수정 버전의 실제 CLI 동작을 확인했습니다.
수정 사항과 웹사이트 전환 검토는 [검증 및 GitHub Pages 전환 보고서](docs/github-pages-review.md)에 정리했습니다.
