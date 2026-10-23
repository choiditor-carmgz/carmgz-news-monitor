# 비공개 Cloudflare 배포 및 진단 결과 (2026-10-23 KST)

후속 상태: API Secrets 등록 후 실제 인증과 Pages 조회 HTTP 200을 확인했다. 현재 남은 실패는 Cloudflare Production 런타임 변수 누락이다. 아래 최초 진단 이후의 변경 사항은 [401 후속 진단](CLOUDFLARE_AUTH_DIAGNOSIS.md)을 우선 참고한다.

## 확인된 원인

- [최근 News operations 39949145526](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/39949145526): main, 성공. 수집·분석·SQLite 저장·dashboard-preview 업로드 성공. publish=false여서 기존 deploy job은 skipped.
- 직전 main 실행 39940416554는 상태 복원 실패로 생성 단계에 도달하지 못했다. 최근 성공 실행에서는 main 상태 아티팩트가 존재한다. initialize를 다시 켜서 초기화할 필요가 없다.
- dashboard-preview 아티팩트 12498939140의 ZIP은 `index.html`, `app.js`, `style.css`, `dashboard.json`을 실제 포함한다. JSON 생성은 정상이다.
- 생성 위치는 `python -m carmgz.operations`의 기본 출력 `site/dashboard.json`. `site/`는 gitignore 대상이다. 소스 `web/` 또는 Git 체크아웃만 배포하면 JSON이 없다.
- Cloudflare 브라우저 `/dashboard.json` 직접 탐색에서 JSON 대신 대시보드 HTML과 동일한 오류 문구를 확인했다. 누락 파일에 대한 Pages SPA 대체 응답과 일치한다. 인증된 요청의 HTTP 코드는 브라우저 도구에서 확인하지 못했으므로 404로 단정하지 않는다.
- 익명 curl GET/HEAD 확인: Cloudflare `/dashboard.json`은 HTTP **302**, 기존 팀의 Access 로그인으로 이동. Access 보호가 작동한다. 인증 정책은 변경하지 않았다.
- 기존 Actions는 `upload-pages-artifact`/`deploy-pages`로 **GitHub Pages**만 배포했다. Cloudflare 업로드 단계가 없었다. 최신 아티팩트 생성 성공은 Cloudflare 배포 성공을 뜻하지 않는다.
- 기존 GitHub Pages `/carmgz-news-monitor/dashboard.json`은 익명 HTTP **200 application/json**이었다. 현재 공개 경로가 남아 있다. 게시 중단 API 작업은 자동 승인 검토에서 외부 사이트 중단 위험으로 거절되어 실행되지 않았다. 사용자 승인 또는 직접 게시 중단이 필요하다.

## 변경된 배포 경로

`News operations → SQLite 복원 → 수집/168시간 정리/분석 → site/ 생성 → dashboard-preview → deploy job 다운로드 → JWT 검증 Worker 번들 → 허용 파일만 cloudflare-dist/ → Wrangler → 기존 carmgz-news-monitor 프로젝트`

- 예약 실행은 main에서 성공한 수집 결과를 자동 배포한다. main 수동 실행은 `publish=true`일 때 배포한다. 개발 브랜치는 수집/아티팩트 검증만 하며 실제 운영 배포를 수행하지 않는다.
- `cloudflare-dist/`의 루트에 HTML·JS·CSS·`dashboard.json`이 나란히 위치한다. 요청은 같은 origin의 `/dashboard.json`이다. 공개 GitHub/raw GitHub/R2 URL로 우회하지 않는다.
- `_worker.js`는 모든 경로에서 기존 Access JWT의 RS256 서명, issuer, audience, exp/iat/sub 및 nbf를 검증한다. `_routes.json`은 `/*` 전체를 포함하고 예외 경로가 없다. 배포 hash/branch alias에서도 서명 없는 요청은 403, 설정 누락은 503이다. 응답은 private, no-store. 기존 Access 정책/이메일 로그인은 그대로 사용한다.
- Pages 배포 전 기존 프로젝트·production branch main·검증 변수 존재 여부를 API로 읽기 확인한다. 프로젝트를 새로 만들거나 정책을 변경하지 않는다.
- SQLite·로그·개발용 HTML은 배포 허용 목록에 없다. 토큰·JSON·SQLite를 Git에 커밋하지 않는다. 아티팩트는 GitHub 다운로드 권한을 따르며 Cloudflare Access로 보호되는 저장소는 아니다. 공개 저장소의 읽기 권한 보유자에게도 데이터를 숨겨야 한다면 아티팩트 저장 방식/저장소 접근 정책은 별도 검토해야 한다.
- 뉴스 수집 코드·cron·168시간 정리·브랜치별 상태 복원/보존 정책은 유지했다. 상태 아티팩트 1일 만료와 24시간 이상 중단 시 복원 불가 가능성도 기존과 같다.

## 사용자 설정

1. [GitHub Actions Secrets](https://github.com/choiditor-carmgz/carmgz-news-monitor/settings/secrets/actions)에 다음을 등록한다. 채팅이나 코드에 토큰을 붙이지 않는다.

   | Secret | 값 |
   | --- | --- |
   | `CLOUDFLARE_API_TOKEN` | Cloudflare 사용자 프로필 → API Tokens → Create Custom Token. **Account / Cloudflare Pages / Edit**, 계정은 해당 계정 하나로 제한. Global API Key 불필요. |
   | `CLOUDFLARE_ACCOUNT_ID` | `76fdbe3d5abb7c6e7799a2292271ce6b` |

2. [기존 Pages 설정](https://dash.cloudflare.com/76fdbe3d5abb7c6e7799a2292271ce6b/pages/view/carmgz-news-monitor/settings/production#general)에서 **Production runtime variables/bindings**에 아래 두 값을 설정한다. Build-time 전용 값이 아닌 Functions/Worker 런타임 변수여야 한다. 로그인 정책을 수정하거나 새 Access 앱을 만들지 않는다.

   | 변수 | 값 |
   | --- | --- |
   | `CF_ACCESS_TEAM_DOMAIN` | `https://dawn-cell-a1cd.cloudflareaccess.com` (현재 로그인에서 확인한 기존 팀 주소) |
   | `CF_ACCESS_AUD` | Zero Trust → Access → Applications → 현재 앱 → Additional settings에서 기존 **Application Audience (AUD) Tag** 복사. 새 키 생성 불필요. |

3. 기존 Pages production branch가 `main`인지 확인한다. Git integration을 사용한다면 Builds/branch control에서 production 자동 Git 빌드와 preview 자동 빌드를 끄고, 이 Actions의 Wrangler 업로드를 배포 경로로 사용한다. Git 빌드가 `web/`만 재배포하여 JSON/Worker를 덮어쓰지 않게 한다. Access 설정은 건드리지 않는다. Wrangler 업로드는 Git 통합 프로젝트에서도 지원된다.
4. GitHub Environments의 `cloudflare-pages` 환경에서 main 배포를 허용한다. 조직 규칙상 reviewer가 필요하면 기존 규칙대로 승인한다. 기존 `github-pages` 환경은 사용하지 않는다.
5. 기존 공개 GitHub Pages는 Settings → Pages → **Unpublish site**로 게시 중단한다. GitHub Pages JSON이 익명 404가 되는지 확인한다. 이 변경 승인 대기 중에는 비공개 전환 완료로 간주할 수 없다. 기존 공개 내용의 외부 복사/캐시를 소급 제거한다는 보장은 없다.
6. 이 브랜치를 검토한 후 사용자가 main 병합을 결정한다. 이번 작업에서는 main에 병합하지 않는다. 병합 전에는 main 예약 워크플로가 이전 코드를 사용한다. 병합 후 News operations → main → `mode=refresh`, `initialize=false`, `publish=true`로 첫 배포를 수행하면 기존 실제 상태를 재사용한다. 이후 예약 실행은 수집 결과를 자동 배포한다.
7. 배포 후 로그인 브라우저에서 `/dashboard.json`이 **200 application/json**, `data_kind=real_rss`인지 확인한다. 루트의 최신 갱신 시각·TOP 10·CARMGZ 상세를 확인한다. 시크릿 창에서는 기존 로그인 이동 또는 403이어야 한다. hash 배포 URL에서도 인증 없는 JSON 200이 없어야 한다.

## 실제 검증

- 최신 아티팩트: 생성 시각 **2026-10-23 20:56:44 KST**, `data_kind=real_rss`, `retention_hours=168`, 관련 기사 **191**, 이슈 **155**. 구조: generated_at/expires_at/last_collection_at, articles, issues, rankings, publishers, briefings, alerts, errors.
- rankings: 주요 10, 확산 10, 산업 10, 급상승 2. 급상승을 임의로 10개로 채우지 않는다.
- 위 최신 실데이터를 외부에 공개하지 않고 **127.0.0.1 전용** 서버에서 브라우저 검증. `수집 결과 확인됨`, 기사 191·이슈 155, 주요 TOP 10 10개 표시. 첫 이슈 ‘발리 전기버스 공급·충전 사업’ 12기사/10매체의 상세·그래프·기사 링크와 CARMGZ 판정 근거가 표시된다. 브라우저 console error 0.
- CARMGZ 실제 상태는 `확인 불가`. ‘검색 응답 검증 실패 또는 접근 불가: 미보도로 판정하지 않음’이 표시된다. 표시 기능의 성공과 CARMGZ 검색 자체의 성공을 구분한다. 배포 수정으로 이를 보도 완료/미보도로 조작하지 않았다.
- 로컬 Python **81개 통과**(Windows cp1252 strict 포함), Node **10개 통과**, JS 구문 검사와 esbuild Worker 번들 생성 성공. 인증 회귀 테스트는 테스트용 RSA 키로 정상·위조·만료·다른 issuer/audience·미래 nbf·설정 누락과 모든 경로 접근 차단을 확인한다. 실사용 인증 토큰을 수집/저장하지 않았다.
- 코드 커밋 `2154875`의 [CI 39957254002](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/39957254002): **Windows·macOS·Ubuntu 전부 성공**. 각 OS에서 Python 81개, Node 10개, Worker 번들 생성 검증. Windows cp1252 strict 검사도 성공.
- 현재 GitHub Secrets/Variables 목록은 비어 있다. Cloudflare 관리자 인증/API 권한도 제공되지 않았다. 따라서 **실제 Cloudflare 업로드와 업로드 후 로그인 HTTP 200 검증은 미완료**다. 기존 사이트가 이미 수정됐다고 보고하지 않는다.

공식 참고: [CI Direct Upload](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/), [Access JWT 검증](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/), [Git integration에서 Wrangler 사용](https://developers.cloudflare.com/pages/get-started/git-integration/), [preview 보호 범위](https://developers.cloudflare.com/pages/configuration/preview-deployments/).
