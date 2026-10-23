# CARMGZ Auto Mobility News Monitor

Python 3.10+ 표준 라이브러리와 SQLite를 사용하는 다중 언론사 RSS 수집 엔진입니다.
40개 국내 언론사를 후보로 등록하며, 실제 수집 성공·차단·오류·이용 조건 보류·RSS 미확인을 구분합니다.

실행 및 데이터 구조는 [COLLECTOR_README.md](COLLECTOR_README.md), Windows 실측 결과는
[MULTI_SOURCE_VALIDATION.md](MULTI_SOURCE_VALIDATION.md)를 참고하세요.
자동 수집·브리핑·GitHub Pages 대시보드 실행은 [OPERATIONS.md](OPERATIONS.md)를 참고하세요.
운영은 Python 3.12와 브라우저 기본 기능을 사용하며 외부 Python 패키지나 유료 API가 필요하지 않습니다.
예약 실행은 운영 워크플로를 main에 검토·병합하고 최초 상태를 준비한 후 활성화됩니다.
