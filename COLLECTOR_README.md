# CARMGZ Auto Mobility News Monitor — 1단계

Python 3.10 이상, 표준 라이브러리만 사용합니다. API 키, 외부 패키지, 결제수단이 필요 없습니다.
기사 본문·AI 분석·관심도 평가·대시보드는 구현하지 않았습니다.

## 검증 상태 (2026-10-23, 한국 시각)

**실제 기사 수집·저장 검증은 완료되지 않았습니다.** 현재 Google News robots.txt가
일반 User-agent에 대해 / 경로를 금지하며 /rss 예외를 제공하지 않습니다.
프로그램은 이를 감지하면 RSS를 요청하지 않고 오류를 SQLite에 기록합니다.
제공 DB의 실제 기사 수는 0건입니다. 합성 테스트 기사는 임시 DB에서만 사용합니다.
상세 기록은 REPORT.md와 logs/collector.log를 참고하세요.

## Windows 실행

공식 Python 3.10+ 설치 후 이 README가 있는 폴더에서 PowerShell 실행:

~~~powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m carmgz --config config.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

## macOS 실행

~~~sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m carmgz --config config.json
.venv/bin/python -m unittest discover -s tests -v
~~~

가상환경은 권장사항이며 외부 의존성이 없으므로 Python으로 바로 실행해도 됩니다.
Windows에서 python 명령이 Microsoft Store로 연결되면 py -3을 사용하세요.
macOS 명령은 호환성을 고려해 작성했으며 이번 환경에서 실행 검증하지 않았습니다.

## 설정

config.json의 keywords 목록을 수정해 검색어를 관리합니다.
기본 검색어: 자동차, 현대차, 기아, 전기차, 배터리, 자율주행, 로봇, 자동차 부품, 모빌리티, 수입차.
한국어/대한민국 피드(hl=ko, gl=KR, ceid=KR:ko)를 요청하며,
lookback_days=7은 검색식에 when:7d를 추가합니다.
지역·검색 결과에는 비한국어 기사가 포함될 수 있으며, 관련성은 RSS 검색 결과에 의존합니다.
RSS는 전체 뉴스 아카이브나 모든 검색 결과의 완전성을 보장하지 않습니다.

- database: 설정 파일 위치 기준 DB 경로. 재실행 시 같은 파일을 열며 데이터를 삭제하지 않습니다.
- interval_seconds: 기본 5초, 최소 2초. robots 요청·각 검색어·재시도 모두 같은 요청 간격을 적용합니다.
- timeout_seconds: 요청 타임아웃 기본 25초.
- retries: 최초 요청 후 추가 시도 기본 2회, 최대 5회.
- lookback_days: 1~365일.

순차 요청만 수행합니다. 429/일부 5xx/연결 오류는 지수 지연 후 재시도하며,
Retry-After 초 또는 HTTP 날짜를 따릅니다. 300초보다 긴 대기는 현재 실행에서 실패 처리합니다.
403 등은 재시도하지 않습니다. 응답은 최대 5MB, DTD/ENTITY는 거부합니다.
robots.txt 확인 실패 시 수집을 중단하고 실패를 기록합니다.
한 검색어가 실패해도 다음 검색어는 계속 확인합니다. 손상된 항목이 있는 피드는
해당 검색어 전체를 오류 처리해 조용한 데이터 누락을 방지합니다.
프로세스 간 OS 파일 잠금으로 동일 DB에 대한 동시 수집을 막습니다.
중단된 실행은 다음 시작 시 interrupted로 표시합니다.

종료 코드 0=모든 검색어 성공, 1=접속/정책/수집 실패, 2=설정 오류.
성공적으로 응답한 빈 피드는 0건 성공으로 기록됩니다.
콘솔과 logs/collector.log에 로그를 남기고 DB에도 실행/검색어별 통계를 기록합니다.

## 데이터 구조와 중복 처리

- articles: SHA-256 고유 ID, 제목, 언론사, RSS 발행 시각, RSS 링크, 최초 수집/마지막 확인 시각.
- article_sources: 수집원과 RSS GUID, 기사 ID, 해당 피드에서의 링크. 여러 wrapper 링크를 보존합니다.
- article_keywords: 기사-검색어 다대다 연결과 연결별 최초/마지막 확인 시각.
- runs: 실행 시작/종료, 상태, 설정 사본, 조회 항목 수/신규 기사/중복/오류 수.
- query_results: 검색어별 통계와 오류 메시지.
- schema_version: 현재 버전 1. 추후 변경은 명시적 마이그레이션을 추가합니다.
- article_metrics: 향후 관측 출처/시각/조회수/댓글 수. 현재 비어 있습니다.
- article_annotations: 향후 분류/점수/분석 방법/부가정보. 현재 비어 있습니다.

시각은 UTC ISO 8601로 저장합니다. 한국 시각은 +09:00로 변환합니다.
RSS 원본 기사 링크가 아니라 Google News 중계 링크일 수 있으며 원문 링크로 가장하지 않습니다.
언론사나 발행 시각이 제공되지 않으면 각각 빈 문자열/NULL로 저장합니다.

먼저 동일 수집원+GUID를 확인하고, 다음으로 정규화한 언론사+제목+발행 시각의 SHA-256을 사용합니다.
발행 시각 또는 언론사가 없으면 쿼리/fragment를 제외한 링크로 식별합니다.
동일 기사 재등장은 마지막 확인 시각만 갱신하고 검색어 연결을 추가/갱신합니다.
동일 제목이라도 언론사가 다르면 다른 기사입니다.
제목/발행 시각과 GUID가 모두 변경된 재송고는 별도 기사로 남을 수 있고,
같은 언론사가 같은 제목/시각으로 내보낸 다른 기사는 하나로 묶일 수 있습니다.
원문 크롤링 없이 완벽한 의미 기반 중복 판별은 보장하지 않습니다.

중복 건수는 이번 실행에서 이미 저장된 기사로 판정한 RSS 항목 수입니다.
조회 항목 수 = 신규 기사 수 + 중복 건수. 오류 수는 실패한 검색어/robots 검사 수입니다.
각 검색어 저장은 하나의 트랜잭션이며 실패 시 해당 저장을 롤백합니다.

## 조회 예시

Python의 sqlite3 또는 SQLite 도구로 data/news.sqlite3를 엽니다.

~~~sql
SELECT title, publisher, published_at, url FROM articles ORDER BY published_at DESC LIMIT 20;
SELECT a.id, a.title, group_concat(k.keyword, ', ') AS keywords
FROM articles a JOIN article_keywords k ON k.article_id=a.id GROUP BY a.id;
SELECT * FROM runs ORDER BY id DESC;
SELECT keyword, fetched, inserted, duplicates, error FROM query_results;
PRAGMA integrity_check;
~~~

## 영속 저장과 GitHub Actions 설계

초기에는 로컬 data/news.sqlite3가 원본입니다. 폴더/DB를 삭제하지 않으면 재실행 후 유지됩니다.
DB/로그는 .gitignore에 포함해 일반 소스 커밋에 넣지 않습니다.
일관된 백업은 sqlite3 backup API로 만듭니다:

~~~sh
python -m carmgz.backup data/news.sqlite3 backups/news-20261023.sqlite3
~~~

기존 백업 파일 덮어쓰기는 거부합니다. 백업을 다른 저장소에 보관한 뒤 복구 시
수집 프로그램을 중지하고 검증한 백업을 설정된 DB 경로로 복사합니다.

GitHub-hosted runner의 작업 폴더는 영구 디스크가 아닙니다.
향후 Actions는 다음 순서로 구성해야 합니다(자동 실행 워크플로는 아직 추가하지 않음).

1. concurrency group을 고정하고 cancel-in-progress=false로 실행을 직렬화합니다.
2. 지정한 영속 저장소의 최신 검증 백업을 내려받아 data/news.sqlite3로 복원합니다.
3. 복원이 실패하면 새 빈 DB로 진행하지 않고 작업을 중단합니다. 최초 초기화만 명시적으로 허용합니다.
4. 수집과 integrity_check 후 backup 명령으로 스냅샷을 만듭니다.
5. 수집이 일부 실패해도 저장된 성공분/오류 기록을 백업합니다.
6. 영속 저장소에 버전별 백업을 업로드하고 성공한 경우에만 최신 버전 포인터를 교체합니다.
7. 보관 기간, 정기 복구 테스트, 업로드 실패 알림을 설정합니다.

무료 초기 대안은 비공개 저장소의 전용 data 브랜치에 SQLite 백업을 직렬 커밋하는 것입니다.
GITHUB_TOKEN의 contents:write 권한, 브랜치 보호와 용량/커밋 증가를 고려해야 합니다.
규모가 커지면 객체 저장소 또는 관리형 DB로 이전합니다.
Actions artifact는 보관 기한이 있으므로 단독 장기 원본으로 사용하지 않고,
cache는 복구 실패/퇴거/갱신 특성 때문에 영속 DB 저장 수단으로 사용하지 않습니다.
Actions 무료 사용량·저장 한도는 계정별 조건을 별도 확인해야 합니다.
어떤 외부 저장소나 유료 서비스도 이번 단계에 연결하지 않았습니다.

## 확장 지점

providers.py의 Provider 계약(name/url/parse)과 Article을 구현하면 다른 RSS/API를 추가할 수 있습니다.
수집 오케스트레이션·HTTP·저장 로직은 분리되어 있습니다.
다른 제공자의 ID는 provider 이름으로 구분하며, 기사 정체성은 제공자에 독립적입니다.
API 인증/페이지네이션/제공자별 스케줄은 해당 어댑터 확장 시 추가합니다.
기존 기사에 조회수/댓글 수를 추정해서 채우지 않습니다.

## 이용 조건

Google 약관: https://policies.google.com/terms?hl=ko
실행 시 확인하는 정책: https://news.google.com/robots.txt
Google News RSS는 안정적인 공식 유료 API 계약/할당량을 제공하는 서비스로 가정하지 않습니다.
5초 간격은 프로젝트의 보수적 기본값이며 Google이 허용한 요청 한도라는 뜻이 아닙니다.
RSS 메타데이터만 요청하며 기사 본문/원문 사이트/우회 엔드포인트는 수집하지 않습니다.
재배포와 상업적 사용은 각 권리자 조건을 별도 확인해야 합니다.
