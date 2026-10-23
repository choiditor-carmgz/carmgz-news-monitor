# Cloudflare API 401 진단 (2026-10-23 KST)

## 실측 결과와 원인 범위

| 항목 | 결과 |
| --- | --- |
| [기존 실패 39962877671](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/39962877671) | 22:38 KST 실행. 수집 성공, check_cloudflare.py의 Pages API 요청에서 HTTP 401. |
| GitHub token Secret 메타데이터 | 22:49 KST 갱신. 값 자체는 조회·출력하지 않았다. |
| [읽기 전용 진단 39966035257](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/39966035257) | 23:01 KST 실행. user token verify **HTTP 200 / active**, Pages 조회 **HTTP 200**. 인증 후 null 설정 처리에서 실패. |
| [수정 후 재진단 39966321733](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/39966321733) | user token verify **HTTP 200**, Pages 조회 **HTTP 200**, 오류 코드 없음. 이후 `CF_ACCESS_TEAM_DOMAIN` Production 런타임 변수 누락으로 실패. 수집·배포 job 모두 skipped. |

**현재 GitHub Secret으로 실제 API 인증과 대상 프로젝트 읽기는 성공했다. 전체 사전 점검과 배포는 성공하지 않았다.** API 읽기 성공이 업로드 쓰기 권한 성공을 보장하지 않는다.

원래 URL·Bearer 헤더에는 오류가 없었다. 이전 401은 Secret 갱신 전 발생했고, 갱신 후 같은 인증 방식으로 성공했다. 과거 Secret 내용은 복구/조회할 수 없어 당시 줄바꿈·잘못된 토큰·만료 등 세부 원인을 확정할 수 없다. 새 코드가 잘못된 토큰을 정상 토큰으로 바꿨다고 주장하지 않는다. Access 이메일 로그인은 사이트 사용자 인증이며 Cloudflare 관리 API 토큰 인증과 별개다.

## 코드에서 수정한 사항

- API origin은 고정 `https://api.cloudflare.com/client/v4`, 헤더는 `Authorization: Bearer <raw token>`이다. Global API Key용 `X-Auth-Key`/`X-Auth-Email`, Access 쿠키, Access service token을 사용하지 않는다. 토큰은 URL에 넣지 않는다.
- `GET /user/tokens/verify`에서 active를 확인하고, 확인되지 않으면 계정 소유 토큰용 `GET /accounts/{account_id}/tokens/verify`를 별도로 시도한다. 검증 API 하나의 실패만으로 토큰 무효를 단정하지 않는다.
- `GET /accounts/{account_id}/pages/projects/carmgz-news-monitor`는 항상 별도 검사한다. 검증 API가 실패해도 Pages 조회 성공은 별도로 기록한다. 반대로 active 토큰이라도 Pages 조회 실패를 성공으로 처리하지 않는다.
- Account ID는 기존 대상 `76fdbe3d5abb7c6e7799a2292271ce6b`와 정확히 일치해야 한다. 로그에는 값 대신 일치 여부만 기록한다. 프로젝트 이름은 코드/배포 명령 모두 `carmgz-news-monitor`이며 응답의 name도 비교한다.
- Secret 공백·줄바꿈·따옴표·Bearer 접두사·숨은 비ASCII 문자는 요청 전에 거절한다. Wrangler와 다른 값으로 인증하지 않도록 토큰을 자동 trim하지 않는다. 형식 검사만으로 토큰의 유효성을 판단하지 않는다.
- 오류 로그는 고정 단계 이름, HTTP 상태, 숫자 Cloudflare 오류 코드와 고정 안내만 출력한다. 외부 오류 message/result/headers, 토큰 ID/값, 응답 원문, 예외 원문·traceback은 출력하지 않는다. 리다이렉트에 인증 헤더를 전달하지 않는다.
- Pages API가 미설정 `deployment_configs`/`production`/`env_vars`를 null로 반환해도 변수 누락을 구체적으로 알려준다.
- News operations에 `diagnose_auth=true` 읽기 전용 모드를 추가했다. 기존 `cloudflare-pages` 환경과 같은 Secrets로 GET 진단만 실행하고 수집/DB 저장/회전/배포는 건너뛴다. 기본값 false이므로 기존 예약 수집 흐름은 유지된다. Access 정책, 뉴스 수집 프로그램, 데이터 보존 정책은 변경하지 않았다.

## GitHub / Cloudflare 설정에서 할 사항

1. **현재 API 토큰을 다시 교체하거나 권한을 넓힐 근거는 없다.** 실제 읽기 인증이 성공했다. GitHub repository Secrets에 두 API Secret이 존재하며, `cloudflare-pages` environment Secrets는 비어 있어 같은 이름의 환경 Secret에 의한 덮어쓰기는 현재 확인되지 않았다. Secret 값은 읽지 않았다.
2. 다시 401이 나오면 실제 실행 ref/시각 및 최신 Secret 갱신 후 실행인지 확인한다. 값에는 raw API Token만 넣고 토큰 식별 ID·Global API Key·Bearer 문구·curl 명령 전체를 넣지 않는다. 사용자 토큰/계정 소유 토큰을 구분해 검증 API 결과를 본다. 만료/활성 시작/폐기/IP 제한은 Cloudflare 화면에서 확인한다. 이미 확인한 Pages Edit 및 올바른 계정 범위를 불필요하게 확장하지 않는다.
3. active 검증 성공 + Pages 실패이면 계정 리소스 범위/프로젝트/Pages 권한을 점검한다. 검증과 조회가 모두 실패하면 토큰·실효 Secret·제약을 먼저 점검한다. 401 하나만으로 특정 원인을 확정하지 않는다.
4. **현재 필요한 설정:** Cloudflare Workers & Pages → `carmgz-news-monitor` → Settings → Production의 런타임 Variables/Bindings에 다음 두 값을 설정한다. GitHub Secrets에 같은 이름을 추가하는 것만으로는 이 런타임 설정이 적용되지 않는다.

   | 런타임 변수 | 값 |
   | --- | --- |
   | `CF_ACCESS_TEAM_DOMAIN` | `https://dawn-cell-a1cd.cloudflareaccess.com` — 현재 사용 중인 팀 주소 |
   | `CF_ACCESS_AUD` | 기존 Access 앱의 Application Audience (AUD) Tag 복사 |

   이번 진단은 첫 누락 변수 `CF_ACCESS_TEAM_DOMAIN`에서 멈췄으므로 AUD가 설정됐는지는 아직 확인되지 않았다. 두 값 모두 확인한다. 새 Access 앱을 만들거나 기존 허용 이메일·로그인 정책을 바꾸지 않는다.
5. 설정 후 위 **읽기 전용 진단 39966321733의 Re-run all jobs**로 API 인증/프로젝트/변수 검사를 다시 확인할 수 있다. 수집·배포 없는 실행이다. 변경을 검토해 main에 반영할지는 사용자가 결정한다. 이번 작업에서는 새 브랜치에만 commit·push하며 main에는 병합하지 않는다.

## 테스트

로컬 Python **90개 통과**(Windows cp1252 strict 포함), Node **10개 통과**. 신규 테스트는 정확한 API URL/Bearer 헤더, 계정 소유 토큰 fallback, active 토큰의 Pages 403, 전체 401, 검증 API 실패와 Pages 성공 구분, Secret 형식/계정 불일치, 외부 오류에 포함된 가상 Secret의 비노출, 리다이렉트 차단, null 런타임 설정을 검증한다. 테스트 토큰은 모두 가상값이다. 실사용 토큰은 GitHub 러너의 Secret 환경변수에서만 사용했다.

최종 코드 `6fdfdcc`의 [CI 39966320714](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/39966320714)는 **Windows·macOS·Ubuntu 모두 성공**했다. 각 OS의 Python/Node 테스트와 Worker 번들 생성, Windows cp1252 strict 검사까지 통과했다.

공식 규격: [사용자 토큰 검증](https://developers.cloudflare.com/api/resources/user/subresources/tokens/methods/verify/), [계정 소유 토큰 검증](https://developers.cloudflare.com/api/resources/accounts/subresources/tokens/methods/verify/), [Pages 프로젝트 조회](https://developers.cloudflare.com/api/resources/pages/subresources/projects/methods/get/).
