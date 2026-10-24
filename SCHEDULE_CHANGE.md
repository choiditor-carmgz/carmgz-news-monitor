# 뉴스 수집 일정 변경 (2026-10-24)

기준: 최신 main `1909812`에서 새 브랜치로 작업. main에는 직접 병합하지 않는다. 아래 시간은 시작 목표이며 대시보드는 수집·분석·기존 Cloudflare 배포 완료 후 갱신된다. GitHub 예약 실행은 지연될 수 있다.

| 작업 | Asia/Seoul | UTC 대응 |
| --- | --- | --- |
| 평일 수집 9회 | 월~금 00, 08, 10, 12, 14, 16, 18, 20, 22시 | 00/08시는 전날 15/23시(일~목), 나머지는 당일 01,03,05,07,09,11,13시(월~금) |
| 주말 수집 3회 | 토~일 09, 15, 21시 | 토~일 00,06,12시 |
| 기존 오전 브리핑 | 월~금 09시 | 월~금 00시 |
| 기존 오후 브리핑 | 매일 17시 | 매일 08시 |

평일 00:00은 요청한 명시적 수집이다. 그 이후 08:00 전까지 추가 수집은 없다. 주말은 09:00 전까지 수집하지 않는다. 월요일 00:00은 일요일 UTC 15:00이며 토요일 00:00 KST 수집은 없다.

## 문법 및 변경 범위

현재 GitHub.com의 [공식 on.schedule 문법](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)은 IANA `timezone`을 지원한다. Action/runner 버전이 아니라 서버의 workflow 문법 기능이며, 이 저장소는 GitHub.com을 사용한다. 각 cron에 `timezone: 'Asia/Seoul'`을 붙여 현지 시간과 요일을 직접 지정했다. UTC fallback이 필요한 구형 Enterprise Server에 배포하는 작업은 아니다.

`operations.yml`의 기존 수집 cron을 제거하고 수집 2개·브리핑 2개의 서로 겹치지 않는 트리거로 정리했다. 기존 브리핑 wakeup을 삭제하면 09/17시 생성 정책이 바뀌고, 이를 scheduled 모드로 두면 추가 RSS 수집이 발생한다. 따라서 해당 두 트리거만 기존 `refresh` 모드로 연결해 브리핑 시각과 수집 횟수를 모두 유지한다. 브리핑 시간창·생성 판단·누락 보충 로직 자체는 변경하지 않았다.

**수집은 평일 9회·주말 3회**, 별도 브리핑 갱신을 포함한 workflow는 평일 11회·주말 4회다. 주간 수집 51회·브리핑 전용 12회, 전체 63회이며 중복 트리거는 없다. 브리핑 전용 실행도 기존 저장·분석·배포 경로를 사용한다.

변경 파일:

- `.github/workflows/operations.yml`: cron/timezone, 브리핑 전용 트리거의 refresh 모드 선택만 변경.
- `carmgz/schedule.py`: 내부 collect 슬롯을 같은 새 일정으로 동기화. am/pm 슬롯 유지.
- `tests/test_operations.py`: 일정·UTC 경계·중복 트리거·수동 기능·오전 회수·브리핑 보존 회귀 테스트.
- `OPERATIONS.md`: 현행 운영 일정과 실행 횟수 설명 갱신.
- `SCHEDULE_CHANGE.md`: 이번 변경·검증 보고.

수집/분류/이슈/TOP 10/CARMGZ 검색/중복 제거/SQLite 복원·보존/168시간 정리/Access JWT/Secrets/런타임 변수/배포 명령은 변경하지 않았다. 수동 mode/initialize/diagnose_auth/redeploy_run_id와 기존 예약 배포 조건을 유지했다. 새로운 알림 기능이나 외부 서비스는 추가하지 않았다.

## 야간 회수 및 검증

수집 엔진은 기존처럼 현재 RSS가 제공하는 최근 7일 기사를 다시 확인하고 중복을 제거한다. 다음 오전 실행에서는 이전 정상 수집 시각을 catchup.since로 기록하며 피드에 남은 야간 기사를 회수한다. RSS에서 사라진 기사까지 복구했다고 기록하지 않는다. 실패·브리핑 전용 refresh는 마지막 정상 수집 시각을 갱신하지 않는다.

14일을 UTC 분 단위로 순회하며 실제 workflow cron의 KST 변환과 내부 슬롯 집합을 대조하고, 각 시각에 정확히 하나의 트리거만 있는지 검사했다. 금요일 00/22시, 토요일 09시, 일요일 21시, 월요일 00/08시의 UTC 날짜를 별도로 검증했다. 평일·주말 가상 RSS 통합 테스트는 야간 신규 기사 회수·재수집 중복 방지·브리핑 시 RSS 호출 금지·마지막 정상 수집 시각·dashboard.json 생성을 검증했다.

로컬 전체 Python **95개**, Node **13개** 통과. 실제 예약 실행은 default branch에 병합한 후 적용되며 개발 브랜치의 테스트 성공을 새 일정의 실제 정기 실행 이력으로 주장하지 않는다. 운영 데이터에 테스트 기사를 넣거나 실제 수집·배포를 시험 실행하지 않았다.

GitHub 서버가 새 timezone 문법을 파싱한 [읽기 전용 기존 진단 실행 40056400701](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40056400701)은 성공했고, 수집·배포 job은 skipped다. 최종 테스트 보강 커밋 `8a5410c`의 [push CI 40056600769](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40056600769)와 [PR CI 40056604163](https://github.com/choiditor-carmgz/carmgz-news-monitor/actions/runs/40056604163)는 Windows·macOS·Ubuntu 모두 성공했다. 각 OS Python 95개·Node 13개·Worker 번들 생성, Windows cp1252 strict 검사까지 통과했다.
