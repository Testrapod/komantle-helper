# 웹 버전 배포 및 운영

## 최초 배포 검증 기록

2026-10-24 (Asia/Seoul)에 [구현 PR #1](https://github.com/Testrapod/komantle-helper/pull/1)을
병합하고 [첫 발행 워크플로](https://github.com/Testrapod/komantle-helper/actions/runs/40085308073)의
build·deploy·record-success 전체 성공을 확인했다.

- 공개 URL: [꼬맨틀 헬퍼](https://testrapod.github.io/komantle-helper/).
- GitHub Ubuntu 환경에서 Python 테스트 33개, Node 테스트 5개, Chromium 시나리오 8개 통과.
- Linux의 Java 21 + Okt 대표 단어 분석 성공.
- 실제 1665~1667회 각각 1,001개 단어 수집 및 품사 분석, `data` 브랜치 영구 저장 성공.
- 공개 URL에서 HTML·CSS·JavaScript·아이콘 HTTP 200과 세 회차 JSON의 SHA256·완전성 검사 통과.
- 브라우저에서 실제 URL의 회차 선택과 초기 힌트 숨김 화면 확인.
- [수동 재실행](https://github.com/Testrapod/komantle-helper/actions/runs/40085497197)에서
  추가 수집 0개·실패 0개, `deploy=false`와 배포 job 생략 확인.

첫 수동·push 발행은 검증했으며, 다음 날짜의 예약 수집 성공은 별도로 확인해야 한다.

## 구조

- `main`: CLI, 웹 소스, 테스트, 빌드·배포 도구.
- `data`: 누적 `manifest.json`, `rounds/<회차>.<SHA256>.json`, 성공 배포 정보 `operations.json`.
- GitHub Pages: 빌드한 `dist/` 전체. 데이터 브랜치 직접 배포는 사용하지 않는다.
- 원본 API는 수집 단계에서만 호출한다. 방문자는 같은 사이트의 JSON을 읽는다.

## 최초 설정

1. 원본 데이터 공개 범위와 이용 조건을 확인한다. API 접근 가능 여부만으로 재배포 허용을 판단하지 않는다.
2. 저장소 Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 설정한다.
3. GitHub Actions가 `data` 브랜치에 쓸 수 있어야 한다. 기본 브랜치 보호를 해제할 필요는 없다.
4. `main`에 워크플로를 반영하고 Actions의 **Collect data and publish Pages**를 수동 실행한다.
5. `collect=true`로 실행한다. `data` 브랜치가 없으면 최초 생성하고 최근 3개 회차를 수집한다.
6. 실행 결과와 Pages의 실제 URL을 확인한다. 기본 URL은 `https://testrapod.github.io/komantle-helper/`다.

Pages API로 설정하려면 저장소 관리 권한이 있는 인증 환경에서 실행한다.

```sh
gh api --method POST repos/Testrapod/komantle-helper/pages -f build_type=workflow
```

이미 Pages가 있다면 `POST`를 반복하지 말고 현재 설정을 읽은 뒤 필요한 필드만 수정한다.
설정 명령만으로 사이트 게시가 완료되는 것은 아니다. Pages 배포 job의 성공을 확인해야 한다.

워크플로 파일을 push할 때 OAuth 토큰에 `workflow` 권한이 필요할 수 있다.
권한 오류가 실제로 발생하면 `gh auth refresh -h github.com -s workflow`로 인증을 갱신한다.
토큰을 저장소 파일이나 워크플로에 직접 기록하지 않는다.

## 정기 실행과 무변경 처리

매일 00:07, 01:07 Asia/Seoul로 예약한다. GitHub 예약은 지연·누락될 수 있다.
공개 저장소는 장기 비활성으로 예약이 꺼질 수 있으므로 오래된 데이터가 보이면 Actions 상태를 확인한다.

실행 시작 시 한국 날짜를 기준으로 오늘 회차를 정한다. 오늘-2부터 오늘까지의 누락만 수집하며,
미래 회차는 수집하지 않는다. 첫 시작 전의 오래된 데이터는 원본 API 제한 때문에 복원되지 않을 수 있다.
수집한 과거 파일은 원본 조회 기간이 지나도 보관한다.

같은 코드 SHA와 같은 manifest 내용이 이미 배포되었으면 새 배포를 생략한다.
오늘이 바뀌면 오늘 파일의 누락을 먼저 수집한다. `operations.json` 갱신은 데이터 식별자에 포함하지 않는다.
수집과 배포를 하나의 발행 워크플로로 연결하므로 봇 push가 다른 워크플로를 다시 트리거할 필요가 없다.

`main`의 웹·수집·배포 코드 변경은 보관 데이터를 재사용하여 배포한다.
아카이브가 아직 없다면 초기 데이터를 수집한다. PR은 합성 데이터로 검증만 하고 게시하지 않는다.
예약 실행은 오늘 데이터가 없을 때 기존 사이트를 유지하지만, 코드 변경은 과거 정상 데이터로도 배포할 수 있다.

## 수동 복구

Actions → **Collect data and publish Pages** → **Run workflow**에서 `main`을 선택한다.

| 목적 | 입력 |
| --- | --- |
| 누락 회차 수집·배포 재시도 | `collect=true`, `force_round` 비움 |
| 보관 데이터로 코드 재배포 | `collect=false`, `force_round` 비움 |
| 특정 회차 데이터 수정 | `force_round`에 회차 입력. 수집 가능한 기간 안의 회차 사용 |

성공한 배포와 데이터가 완전히 같으면 재실행은 아무것도 바꾸지 않는다.
기존 배포가 실패했다면 성공 기록이 없으므로 동일한 코드·데이터로도 다시 시도한다.

일부 회차 수집이 실패해도 정상 회차는 먼저 `data`에 저장한다.
오늘 파일이 없으면 예약 실행은 그 후 실패로 끝나고 기존 Pages를 유지한다.
오늘 파일이 있으면 일부 과거 회차의 실패는 실행 요약에 남기고 정상 데이터로 배포한다.
HTTP 429·일시적 서버 장애는 제한 횟수만 재시도하고, `Retry-After` 대기는 최대 10초로 제한한다.

수집 후 저장만 성공하고 배포가 실패해도 저장한 파일은 남는다.
원격 `data` 브랜치가 외부에서 동시에 수정되어 push가 거절되면 덮어쓰지 않고 실패한다.
다음 실행에서 최신 브랜치를 읽어 다시 시도한다. 자동 강제 push·과거 데이터 삭제는 하지 않는다.

## 코드·데이터 오류 복원

- UI 오류: 정상 코드로 revert하여 `main`에 반영하고 배포한다.
- 데이터 오류: 조회 가능 기간이면 특정 회차 강제 재수집. 이전 해시 파일은 그대로 남긴다.
- 조회 기간이 지난 데이터 오류: `data` 이력에서 정상 파일과 manifest를 복원하고 수동 배포한다.
- 브랜치 손상: 새 빈 아카이브를 덮어쓰지 않는다. 기존 원격 이력 또는 백업으로 복구한다.
- 예약 전체가 중단된 경우: 공개 페이지에는 마지막 성공 데이터의 날짜만 표시할 수 있다.
  사이트의 갱신 대기와 GitHub Actions의 활성 상태를 함께 확인한다.

`operations.json`은 실제 성공한 배포의 코드 SHA·데이터 식별자를 기록한다.
직접 아카이브를 수정할 때 이 파일을 성공한 것처럼 갱신하지 않는다.
성공 기록만 저장하지 못했다면 다음 실행에서 배포가 한 번 중복될 수 있다.

## 로컬 검증 및 게시 전 점검

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m pip check
npm ci
npm test
npx playwright install chromium
python -m scripts.demo_data
python -m scripts.build_site --archive-dir .demo-archive --output .preview/komantle-helper
npm run test:e2e

# 실제 API와 Java: 명시적으로 실행
python -m scripts.collect_data --archive-dir .archive --result collection-result.json
python -m scripts.build_site
```

`collection-result.json`의 `failed_rounds`가 비었는지 확인한다. 회차별 실패는 구조화된 결과로
반환하므로 수집 명령의 종료 코드 0만으로 오늘 데이터 준비를 판단하지 않는다.
일반 CI에서는 외부 API를 호출하지 않으며, Ubuntu의 Java/Okt 대표 단어 분석은 별도로 검증한다.
브라우저 테스트는 실제 Pages와 같은 `/komantle-helper/` 경로에서 실행한다.

첫 배포와 다음 날 자동 갱신은 서로 다른 검증이다. 최초 배포 후 다음 한국 날짜에
새 회차가 추가되고 기존 파일이 유지되는지 확인한다. 이 저장소의 코드 구현만으로
미래 예약 실행의 성공까지 확인된 것으로 간주하지 않는다.

## 크기와 데이터 노출

2026-10-24 로컬 실제 수집 결과, 회차당 JSON은 약 121~125KB이며 3회차를 포함한 사이트는 약 399KB였다.
이 속도라면 신규 회차 365개의 원본 JSON은 대략 45MB이며, Git 이력과 수정본은 별도다.
Pages 용량을 관찰하고 장기 보관 위치가 필요해지면 별도로 분리한다.

단어·정답은 JSON에 공개된다. UI의 힌트 버튼과 확인창은 실수로 보는 것을 줄이는 기능이다.
스크린리더 레이블·초기 DOM·URL에 숨긴 단어를 미리 삽입하지 않는다.
실행 로그에는 회차·개수·성공 여부만 출력하고 전체 정답 목록을 출력하지 않는다.
