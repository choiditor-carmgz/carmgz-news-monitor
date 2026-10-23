# 뉴스 관심도 분석

자동 운영 및 7일 보관 정책은 [OPERATIONS.md](OPERATIONS.md)를 우선 참고한다. 아래 수동 JSON/CSV 내보내기 결과는 로컬 분석용이며 Git 추적과 Pages 배포에서 제외한다.

기존 Python 표준 라이브러리·SQLite 수집 엔진을 유지한다. 분석은 DB를 읽기 전용으로 열며 원본 기사와 수집 기록을 변경하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m carmgz.analysis
# 저장된 수집 시점 재현
.\.venv\Scripts\python.exe -m carmgz.analysis --as-of 2026-10-23T05:26:21.332861+00:00
.\.venv\Scripts\python.exe scripts/build_analysis_report.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

`--database`, `--publishers`, `--output` 경로를 지정할 수 있다. 기본 기준 시각은 현재 UTC이며 오래된 데이터로 현재 급상승 순위를 꾸미지 않는다. 커밋한 결과는 명시한 과거 수집 시각의 재현본이다. 재현 보고서 스크립트는 이 저장된 데이터셋에 관한 설명을 포함하므로 다른 데이터셋에는 설명도 갱신해야 한다.

JSON에는 기사별 판정·원문 URL, 모든 이슈와 개별 기사, 시간창·성장률·전재/반응 지표 및 세 가지 TOP 10이 담긴다. CSV는 articles, publishers, issues, top10_spread, top10_rising, top10_industry로 구분한다. null은 CSV에서 빈 칸이며 0은 관측된 0이다. 반응 지표는 기존 article_metrics의 최신 관측값과 관측 범위를 사용하며 수집 가능한 API가 아직 연결되지 않았다. 부분 확보 시 합계와 coverage를 함께 확인해야 한다.

사건 통합과 산업 중요도 규칙은 `carmgz/analysis.py`의 EVENTS·IMPORTANCE에 명시한다. 새 사건에 맞는 앵커가 없으면 별도 이슈로 남기는 보수적인 방식이다. 본문·배포 출처 미확보 상태에서 전재율이나 독립 취재 비율은 산출하지 않는다. 매체 수는 서로 다른 등록 언론사 명칭 수이며 기업 소유관계가 검증된 독립 언론사 수는 아니다.

실제 데이터의 전체 TOP 10·매체별 수집 실패·누락 점검은 ANALYSIS_REPORT.md 참조. 테스트 자료는 가상 fixture이며 실제 JSON/CSV에는 사용하지 않는다. 웹 대시보드와 자동 실행은 포함하지 않는다.
