# CARMGZ Auto Mobility News Monitor

Python 3.10+ 표준 라이브러리와 SQLite를 사용하는 다중 언론사 RSS 수집 엔진입니다.
122개 국내 언론사를 후보로 등록하며, 실제 수집 성공·차단·오류·이용 조건 보류·RSS 미확인을 구분합니다.

실행 및 데이터 구조는 [COLLECTOR_README.md](COLLECTOR_README.md), Windows 실측 결과는
[MULTI_SOURCE_VALIDATION.md](MULTI_SOURCE_VALIDATION.md)를 참고하세요.
자동 수집·브리핑·GitHub Pages 대시보드 실행은 [OPERATIONS.md](OPERATIONS.md)를 참고하세요.
운영은 Python 3.12와 브라우저 기본 기능을 사용하며 외부 Python 패키지나 유료 API가 필요하지 않습니다.
예약 실행은 운영 워크플로를 main에 검토·병합하고 최초 상태를 준비한 후 활성화됩니다.
## 120개 매체·CARMGZ 취재 관리 확장

일반 수집 후보 122개와 제외 매체 보존 행 1개를 `publishers.json`에서 관리합니다. 등록 수는 실제 수집 성공 수와 다릅니다. 매체별 검증 상태·공식 RSS 근거는 [매체 목록](PUBLISHER_REGISTRY.csv), 구현/실측/제약은 [구현 결과](IMPLEMENTATION_REPORT.md)를 참고하세요.

`python -m carmgz.operations`는 수집·이슈 분석 후 날짜 제한 없는 CARMGZ 공식 검색을 실행하고 브리핑·정적 대시보드에 판정을 포함합니다. 검색 예산·불완전성을 명시하며 결과 0건을 미보도로 단정하지 않습니다. 기존 DB는 먼저 백업하고 검증용 사본에서 운영 명령을 시험하세요.

신규 두 매체의 제약과 브랜치별 수동 운영·Pages 승인 절차는 [운영·배포 결과](RELEASE_REPORT.md)를 참고하세요.
