# 분석 보고서 보관 방식 변경

기사 제목·URL·개별 TOP 10을 담은 과거 보고서는 최근 7일 보관 정책에 맞춰 현재 Git 트리에서 제거했다. 원본은 로컬 `data/legacy/ANALYSIS_REPORT.md`에 이관 확인용으로 보존했다. 이전 커밋의 내용은 이력 재작성 없이는 사라지지 않는다.

앞으로 실데이터는 SQLite 운영 상태와 만료되는 대시보드 JSON·브리핑에만 저장한다. 운영 방법과 보관 제약은 [OPERATIONS.md](OPERATIONS.md), 이번 기능 검증은 [OPERATIONS_VALIDATION.md](OPERATIONS_VALIDATION.md)를 참고한다.
