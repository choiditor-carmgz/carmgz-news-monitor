# 다중 언론사 RSS 수집 엔진

Python 3.10 이상, 외부 의존성 없음. 기사 본문을 요청하지 않으며 RSS 제목·언론사·발행 시각·URL만 저장합니다.
기존 Google 어댑터와 18개 테스트, 기존 SQLite 테이블, 백업 및 프로세스 잠금은 유지합니다.
기본 실행은 Google을 사용하지 않습니다.

## Windows 실행

```powershell
.\.venv\Scripts\python.exe -m carmgz --config config.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m carmgz.discover
```

설치된 Python이 있다면 `py -3 -m venv .venv`로 환경을 만들 수 있습니다.
마지막 명령은 공식 홈페이지/RSS 안내 페이지의 RSS·제휴 안내 링크를 조사합니다.
기사 페이지 순회나 자동으로 발견한 URL의 무조건 수집은 수행하지 않습니다.

## 언론사 추가 및 상태

publishers.json에 고유 id, publisher, category, feed_url, official_reference,
rss_status, enabled, permission을 추가합니다. RSS/Atom은 공통 PublisherRSS로 처리하며,
특수 포맷은 별도 어댑터로 확장할 수 있습니다. 한 피드 실패는 다음 언론사에 영향을 주지 않습니다.
공식 안내 여부와 실제 HTTP·파싱 결과는 서로 독립적인 정보입니다.
미확인은 RSS가 없다는 확정 판정이 아닙니다. 홈페이지 링크 탐색에도 누락이 있을 수 있습니다.
공식 RSS 링크를 찾지 못하면 enabled=false로 유지하고 공식 계약/API 허용 여부를 확인합니다.
뉴스1은 CONNECT 계약형 공급 서비스가 확인됐지만 계약이나 API 권한은 확보하지 않았습니다.

robots는 각 origin에서 실행마다 검사합니다. 리디렉션 목적지도 검사합니다.
404/410 robots는 제한 없음으로 처리하며, 403/429/오류/해석 불가 정책은 수집하지 않습니다.
robots의 다른 호스트 리디렉션은 수동 검토 대상으로 보류합니다.
TLS 인증서 검증을 유지하고 User-Agent 위장·프록시·차단 경로 우회는 하지 않습니다.
기본 간격 5초, 피드별 타임아웃 12초, 현재 재시도 0회이며 설정으로 변경 가능합니다.
상세 HTTP 요청 증거는 reports/latest.json의 requests와 SQLite feed_checks에 남습니다.
robots 허용은 상업적 사용/재배포 허가를 의미하지 않습니다.
SBS·경향신문·이투데이는 확인한 이용 제한 때문에 기본 비활성화했습니다.

config.json의 keywords는 제목 부분 문자열 필터입니다. 본문은 저장하지 않습니다.
배터리·로봇 같은 넓은 검색어와 기아 같은 동음이의어는 오탐이 있을 수 있으며,
제목에 검색어가 없는 관련 기사는 누락될 수 있습니다. AI 분류로 가장하지 않습니다.
lookback_days는 발행 시각 기준 보존 대상 범위입니다. 시각 누락 항목은 보존합니다.
파싱한 전체 항목 수와 범위 내 관련 기사 수를 구분하고, 전부 오래된 피드는 stale_feed입니다.
발행 시각은 UTC ISO 8601로 저장하며 시간대가 없는 국내 날짜는 한국 시각으로 해석합니다.

## 저장·중복·갱신

기존 DB를 삭제하지 않고 schema_version=2 테이블을 추가합니다.

- articles, article_sources, article_keywords, runs, query_results 및 기존 지표/주석 테이블 유지.
- publishers: 언론사 설정 사본. feed_checks: 실행·언론사별 결과 및 HTTP 증거 이력.
- article_fingerprints: 언론사별 URL·정규화 제목 인덱스.
- article_revisions: 동일 기사 변경 시 이전 제목·발행 시각·URL 보존(관측/보관 시각 포함).
- article_relations: 언론사가 다른 동일 정규화 제목을 '유사성 미확정' 근거로 연결.
- issues, issue_articles: 추후 이슈 식별자와 기사 연결을 위한 빈 테이블.

동일 언론사의 동일 GUID → 동일 canonical URL → 48시간 이내 동일 정규화 제목 순으로
기존 기사를 찾습니다. [종합/속보/재송/수정/업데이트] 표시는 제목 비교에서 제외합니다.
URL의 기사 식별 쿼리는 보존하며 utm_*, fbclid, gclid와 fragment만 제외합니다.
동일 기사 반복 관측은 최초 수집 시각을 유지하고 last_seen_at을 갱신합니다.
제목/URL/발행 시각 변경 전 값은 revisions에 남고 피드별 원래 GUID/URL은 sources에 남습니다.
다른 언론사 기사는 제목이 같아도 합치지 않습니다. 의미가 비슷하지만 제목·GUID·URL이
모두 달라진 재송고는 별도로 남을 수 있습니다. 같은 언론사의 동일 제목 기사가 48시간 이내
실제로 별개 기사일 때는 잘못 합칠 수 있습니다. 본문 없는 메타데이터 판별의 한계입니다.

## 향후 확산 통계에 필요한 근거

issue_articles 연결이 확보되면 이슈별 기사 수, DISTINCT publisher 수, 발행 시간대별 건수,
시간 구간별 증가량/속도 및 언론사별 비중을 계산할 수 있습니다. 실제 이슈 분류는 구현하지 않았습니다.
언론사 수는 독립 취재 보도 수와 같지 않습니다. 동일 제목 관계는 전재의 확정 증거가 아닙니다.
원문 전재 여부는 출처/본문 사용권 등 추가 근거를 확보한 뒤 method와 evidence를 추가해야 합니다.
독립 보도·전재 건수는 현 단계에서 미확정이며 0으로 단정하거나 추정치로 채우지 않습니다.
조회수·댓글 수는 RSS에서 검증 가능한 수치를 확보하지 않아 기존 article_metrics를 비워 둡니다.

## 실행 결과·운영

reports/latest.json은 최근 실행의 언론사별 HTTP/정책/파싱/전체 항목/관련 항목/신규 저장/실패 원인입니다.
SQLite feed_checks는 누적 이력이며 query_results/runs의 fetched는 저장 대상 관련 항목 기준입니다.
전체 피드 항목 합계는 feed_checks.fetched를 사용합니다. 보류/미확인 후보는 errors에 넣지 않으므로
종료 코드 0은 활성 피드 실행 성공을 의미하며 모든 후보의 RSS 확보를 뜻하지 않습니다.
실패가 있으면 종료 코드 1, 설정 오류는 2입니다. empty_feed/stale_feed는 정상 최신 수집과 다릅니다.

DB·로그는 Git에서 제외됩니다. JSON 보고서에는 기사 본문이나 전문이 없습니다.
`python -m carmgz.backup data/news.sqlite3 backups/news.sqlite3`로 일관된 백업을 만들 수 있습니다.
기존 REPORT.md와 LIVE_COLLECTION_TEST_2026-10-23.md는 이전 Google 단독 검증의 역사 기록입니다.
이 엔진은 자동 스케줄·대시보드·AI 분석·외부 배포를 추가하지 않습니다.
