# 실제 Worker 런타임 진단·수정 (2026-10-24 KST)

## 확인된 근본 원인과 현재 상태

오류는 `cloudflare/worker.mjs`의 `createHandler()` 설정 검사에서 반환한 HTTP 503이었다. 기존 코드는 Secret 두 개의 존재 여부뿐 아니라 팀 도메인이 `https://<team>.cloudflareaccess.com` 형식인지 검사했다. 따라서 **Secret 존재와 이 검사 통과는 서로 다르다.**

실제 Production Worker의 값 없는 진단으로 아래를 확인했다.

- `team_present=true`, `audience_present=true`, `assets_present=true`: 두 Secret과 ASSETS가 실제 런타임에 전달된다.
- `team_original_format_valid=false`, `team_normalized_valid=true`: 기존 팀 도메인의 입력 형식이 기존 정규식과 맞지 않았다. 수정 코드는 bare hostname/주변 공백/끝 슬래시를 안전하게 정규화하고, 최종 issuer를 정확한 Cloudflare Access HTTPS origin으로만 제한한다.
- 정규화 후 **503은 해결됐다.** 이후 `assertion_present=true`, `jwt_error=ERR_JWT_CLAIM_VALIDATION_FAILED`, `claim=aud`가 확인됐다.
- `audience_original_hex_tag=false`, `audience_normalized_hex_tag=false`: 현재 Production AUD는 단순 JSON 따옴표 정규화 후에도 64자리 hex 태그 형식이 아니며 실제 로그인 JWT의 aud와도 다르다. Secret 값·JWT·실제 claim 값은 출력하지 않았다.

따라서 503의 원인은 Secret 미등록이 아니라 **팀 도메인 형식에 대한 코드의 지나치게 엄격한 가정**이었다. 추가로 **기존 Production AUD 값 불일치**가 드러났다. 토큰의 aud를 자동 신뢰하거나 audience 검증을 제거하여 이를 우회하지 않는다. 현재 인증된 요청은 이 불일치 때문에 HTTP 403이며, 전체 서비스 정상화를 완료했다고 주장하지 않는다.

## 실제 조사한 배포 경로

- [기존 #18 / 40049548784](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40049548784): operate·deploy 성공. 원본 dashboard-preview ZIP은 `index.html`, `app.js`, `style.css`, `dashboard.json`을 포함한다. JSON은 실제 RSS 기사 213건이다.
- 기존 인증 Worker는 deploy job에서 `pnpm run build:guard`로 생성되므로 원래 dashboard-preview에는 들어 있지 않았다. Wrangler에는 생성한 Worker를 포함한 `cloudflare-dist/`를 전달했다. 원래 503 고유 문구 자체도 Worker 실행의 증거다.
- 저장소에 별도 Wrangler 설정 파일은 없다. 실제 명령은 `wrangler pages deploy cloudflare-dist --project-name carmgz-news-monitor --branch main`이며 기존 프로젝트의 Production branch가 main이므로 Production binding을 선택한다. Workers의 별도 프로젝트로 배포하는 경로가 아니다.
- [읽기 전용 진단 40050103904](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40050103904): 프로젝트 Production 설정, canonical 배포, deployment 상세에 두 Secret 이름이 모두 존재한다. canonical environment=production, branch=main. Preview binding은 없었다. Preview Access 정책과 Preview 런타임 binding은 서로 별개다.
- [최종 런타임 배포 40050685330](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40050685330)은 새 브랜치의 Worker와 **기존 #18 아티팩트**를 사용했다. operate·DB 복원·수집·상태 회전은 모두 실행하지 않았다. main Git 코드는 변경/병합하지 않았다. 같은 기존 Production 프로젝트에 런타임 수정본을 배포했다.
- 실제 배포 URL은 `https://ee3b49de.carmgz-news-monitor.pages.dev`이며 배포 후 대표 주소의 런타임에서 수정본을 확인했다.
- 새 `cloudflare-deployment-bundle` 아티팩트에는 `_worker.js`, `_routes.json`, HTML/JS/CSS, `dashboard.json` 전부가 포함된다. `_routes.json`은 `include=["/*"]`, `exclude=[]`이다.
- 원본 #18과 최종 업로드 JSON의 SHA-256은 둘 다 `a6b29bbde6319383f118e475d33e432b0ac7bd4cc8425e4df0c44cf87166860e`로 동일하다. 뉴스 데이터를 수정하거나 새로 생성하지 않았다.

## 수정 내용·보안

- `env.CF_ACCESS_TEAM_DOMAIN`/`env.CF_ACCESS_AUD`를 직접 읽는다. Secret을 process.env나 빌드 상수로 대체하지 않는다. Secret 값을 번들에 기록하지 않는다.
- 팀 도메인을 정규화하되 다른 host, HTTP, 자격 증명 포함 URL, 경로가 붙은 URL은 계속 거절한다. AUD는 명시적으로 설정된 값의 주변 공백과 JSON 문자열 인용만 정규화한다. JWT에서 허용 audience를 가져오지 않는다.
- `GET /__diagnostics/access-config`는 정상 JWT 검증 후에만 HTTP 200을 반환한다. 실패는 403, 잘못된 설정은 503이다. 정상/실패 진단 모두 존재·형식·일치 여부의 boolean과 고정 오류 분류만 포함하며 실제 값/claim/이메일/기사 데이터는 없다.
- 모든 HTML·JSON·별칭 경로에 RS256 서명, issuer, audience, exp/iat/sub/nbf 검증과 private/no-store를 유지한다. 정책·기존 프로젝트·GitHub Secrets는 수정하지 않았다.
- 읽기 전용 메타데이터 진단, 성공한 main 실행의 기존 데이터만 재배포하는 명시적 `redeploy_run_id` 모드, 최종 번들 보관을 추가했다. 기본 예약 수집 흐름은 그대로다.

## 실제 요청 검증

| 요청 | 결과 |
| --- | --- |
| 대표 주소, 익명 HTML | HTTP 302, Access 로그인으로 차단 |
| 대표 주소 `/dashboard.json`, 익명 | HTTP 302, 데이터 미제공 |
| 대표 주소 JSON, 위조 Cf-Access-Jwt-Assertion | HTTP 302, 데이터 미제공 |
| 로그인 브라우저, 수정본 진단 경로 | HTTP 403, 실제 JWT aud와 설정값 불일치 확인 |

CI 녹색은 업로드 성공의 증거이며 위 표의 인증된 요청 성공을 대신하지 않는다. 현재 인증된 HTML·JSON HTTP 200은 **미완료**다.

## 추가로 필요한 사용자 작업

Cloudflare Pages → 기존 `carmgz-news-monitor` → Production의 **CF_ACCESS_AUD 값만** 기존 대표 주소 Access 앱의 **Application Audience (AUD) Tag**와 대조·수정한다. 토큰 식별 ID, 앱 ID, 변수 이름, Bearer 문자열을 넣지 않는다. 실제 값은 채팅·로그에 보내지 않는다. 기존 허용 이메일·Access 정책·GitHub Secrets를 바꿀 필요는 없다.

Secret 변경은 다음 배포부터 적용될 수 있으므로, 수정 후 이 브랜치의 News operations에서 `redeploy_run_id=40049548784`로 기존 데이터만 재배포한다. Secret 변경을 확인하지 못한 상태에서 자동으로 재등록하거나 정책을 변경하지 않았다. 해당 아티팩트가 만료됐으면 다른 성공한 main 실행의 아티팩트 ID를 선택해야 한다.

수정 브랜치는 main에 병합하지 않았다. main의 기존 Worker가 예약 배포되면 런타임 수정본이 다시 덮어써질 수 있으므로, PR 검토 후 사용자가 병합해야 이후 자동 배포에도 코드 수정이 유지된다.

## 테스트

[최종 코드 f3f9bf8의 CI 40050684731](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40050684731): Windows·macOS·Ubuntu 모두 성공. Python **92개**, Node **13개**, Worker 번들 생성과 Windows cp1252 strict 검사 통과. 테스트는 bare hostname/공백/인용 정규화, 다른 origin·위조·만료·잘못된 issuer/audience 차단, 진단 경로 보호와 비노출, 기존 데이터 소스 검증을 포함한다.

공식 참고: [Pages Advanced mode와 env](https://developers.cloudflare.com/pages/functions/advanced-mode/), [Pages Secret binding](https://developers.cloudflare.com/pages/functions/bindings/). 공식 문서상 Secret은 runtime env에 주입되며 새 deployment에 적용된다. 이번 조사에서는 문서만으로 추정하지 않고 배포 API 메타데이터와 실제 Worker 요청으로 검증했다.
