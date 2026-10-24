# 단어 채점 API

GitHub Pages는 기존 정적 화면과 회차 JSON을 계속 제공한다.
상위 1,000위에 없는 추측 단어의 정확한 점수를 얻을 때만 이 API를 호출한다.
API는 원본의 고정 경로 `https://semantle-ko.newsjel.ly/guess/<회차>/<단어>`를 조회한다.
클라이언트가 임의 URL이나 요청 헤더를 지정할 수 없으며, 사용자 쿠키·인증 정보를 원본에 전달하지 않는다.

## 관리 대상

- Sites 프로젝트: `.openai/hosting.json`의 `project_id`를 그대로 재사용한다. 새 Site를 중복 생성하지 않는다.
- 주소: `https://komantle-helper-scoring-api.eastsea-y.chatgpt.site`.
- 메서드·경로: `POST /api/guess`, CORS 사전 요청을 위한 `OPTIONS /api/guess`.
- 웹 호출 설정: 저장소의 `web/config.js`.
- 공개 접근 상태는 Sites 프로젝트 설정으로 제어한다. 비공개 상태에서는 일반 Pages 방문자의 요청이 차단된다.
- 플레이어 기록은 웹 localStorage 및 CLI 로컬 파일에만 저장한다. API에는 플레이어 기록 DB가 없다.
  동일 단어·회차의 성공 응답은 플랫폼 캐시에 최대 하루 보관할 수 있다.

## 계약

```json
{"round":1667,"word":"사과"}
```

성공 응답의 축약 예시:

```json
{"word":"사과","similarity":12.96,"rank":null,"correct":false}
```

유사도는 -100~100이고 `rank`는 정답이면 0, 상위 1~1000위이면 정수, 정확한 순위가 없으면 null이다.
원본이 반환한 점수를 사용하며, 알 수 없는 단어·오래된 회차·서버 장애를 0점으로 바꾸지 않는다.

브라우저 출처는 `https://testrapod.github.io`만 허용한다.
CORS는 브라우저 제한이며 API 자체의 인증이나 악용 방지 수단으로 간주하지 않는다.
API를 공개하면 URL을 아는 외부 클라이언트도 유효한 채점 요청을 보낼 수 있다.
입력 길이·회차·응답 형식·시간 제한을 검사하고, 범용 프록시 기능은 제공하지 않는다.

## 소스와 재배포

`handler.js`는 플랫폼에 의존하지 않는 실제 채점 처리 코드이며 Node 단위 테스트에서 검증한다.
`route.ts`는 Sites 서버 런타임의 HTTP 라우트 연결 코드다.
`.openai/hosting.json`은 인증 정보가 없는 프로젝트 식별 정보다. 서비스 인증 토큰은 GitHub에 저장하지 않는다.

배포용 `api-service/`는 GitHub에서 제외한 별도 Sites 소스 checkout이다.
프로젝트가 없는 새 로컬 환경에서는 Sites 스킬의 기본 서버 템플릿으로 `api-service/`를 준비하고,
기존 프로젝트 ID의 소스 저장소를 연결한다. 프런트엔드를 Sites로 옮기지 않는다.

```sh
# 저장소 루트에서, 템플릿 준비 후 실행
python -m scripts.prepare_api_service
```

이 명령은 추적 중인 handler·route·hosting manifest와 서비스 소개 페이지를 배포 checkout에 동기화한다.
Sites의 source helper로 정확한 소스를 commit/push하고 `build-site.mjs`로 빌드·패키징한 다음,
저장한 버전 ID를 사용해 배포한다. 비공개 상태는 비공개 배포 도구로 유지한다.
접근 대상을 공개로 변경하려면 별도의 명시적 승인이 필요하다.

일반 GitHub CI는 실제 API에 의존하지 않고 원본 채점·프록시 응답을 모의 처리한다.
배포 후에는 실제 단어 하나로 점수와 CORS 헤더를 확인하고, 공개 승인 후에는
GitHub Pages에서 로그인 없이 채점할 수 있는지 브라우저로 확인한다.

## 기존 브랜치

`codex/github-pages-web`은 초기 웹 버전을 개발한 작업 브랜치다.
PR #1로 `main`에 병합되었으며, GitHub Pages가 이 브랜치를 직접 서비스하는 것은 아니다.
Pages 배포 소스는 `main`의 웹 코드와 `data` 브랜치의 보관 JSON이다.
