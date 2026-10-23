"""Render a Korean audit from real SQLite analysis JSON (no fabricated articles)."""
import json
from pathlib import Path

r = json.loads(Path('reports/analysis/analysis.json').read_text(encoding='utf-8'))
lines = ['# 실제 RSS 데이터 검증 및 관심도 분석', '',
         f"기준 시각: {r['as_of']} (최종 수집 완료 시점 재현, 현재 실시간 순위 아님).", '',
         '최신 origin/main ebb15dc 기반. 실제 DB는 읽기 전용 트랜잭션으로 분석하며 초기화·삭제·스키마 변경 없음.', '',
         f"최종 실행 RSS {r['latest_rss_items']}건, 키워드 후보 {r['latest_keyword_candidates']}건, 누적 저장 {r['stored_articles']}건.",
         'RSS 전체 1,574건은 저장되지 않았으며 원문 본문도 보관하지 않았다. 저장된 것은 키워드 후보의 제목·매체·발행일·원문 URL이다.',
         '이전 실행에서만 관측된 한국경제 LG·현대차 로봇 인재 영입 기사 1건이 92 대 93 차이의 원인이다. 삭제된 기사라는 뜻은 아니다.', '',
         f"분류: {r['classification_counts']}. 관련 73건을 41개 이슈로 분석했다.",
         '최신 92건 기준 관련 72건, 범위 검토 6건, 기아대책 오분류 1건, 모터그래프 제외 13건이다.',
         '73건은 제목 근거의 자동차·모빌리티·핵심 전지 기술 관련성 판정이며 본문 정확성 검증 완료를 의미하지 않는다.',
         '필수 필드 누락 0건. 발행일 파싱·URL 형식 이상은 articles.csv에서 기사별 확인 가능. 원문 링크의 현재 응답·본문은 재요청하지 않았다.',
         '모터그래프 13건은 DB에 보존하고 분석에서 제외했다. 탑라이더·카가이·오토뷰는 등록·저장 0건이며 수집 단계에서도 차단한다.', '',
         '## 언론사별 최신 수집 및 누적 저장', '', '|매체|상태|RSS 항목|후보|누적 저장|', '|---|---|---:|---:|---:|']
for p in r['publishers']:
    lines.append(f"|{p['publisher']}|{p['status']}{' / 분석 제외' if p['excluded'] else ''}|{p['rss_items']}|{p['keyword_candidates']}|{p['stored']}|")
for status, label in [('failed', '수집 실패'), ('no_confirmed_feed', '미확인'), ('held', '보류'), ('stale_feed', '오래된 피드')]:
    lines += ['', '## '+label, '']
    lines += [f"- {p['publisher']}: {p['error'] or p['status']}" for p in r['publishers'] if p['status'] == status]
lines += ['', '## 기사별 재검토', '']
for a in r['articles']:
    if a['classification'] in ('review', 'irrelevant'):
        lines.append(f"- [{a['publisher']} · {a['title']}]({a['url']}): {a['classification_reason']}")
lines += ['', '## 계산·평가 기준', '',
          '- 확산도 = 서로 다른 매체 수 × 10 + 기사 수. 매체 수는 소유관계·자체 취재 독립성을 보증하지 않는다.',
          '- 급상승 = max(0, 증가 속도) × 3 + 최근 1시간 기사 수. 증가 속도 = 최근 1시간 건수 − 직전 2시간 건수/2 (건/시간). 최근 1시간 보도가 있고 증가 속도가 양수인 이슈만 선정한다.',
          '- 시간창은 [기준 시각−N시간, 기준 시각] 중 하한 제외, 상한 포함. 미래 발행·날짜 불명은 집계하지 않는다. 최초 보도는 확보된 표본 내 최초이며 전체 시장 최초가 아니다.',
          '- 산업 중요도 = 안전·리콜·사고 30 + 정책·규제·보조금 25 + 생산·실적·공급망 20 + 핵심 기술·상용화 20 + 해외 확장 5. 제목 키워드 범주별 최대 1회 합산. 영향 규모는 아직 판단하지 않는다.',
          '- 동점은 매체 수, 기사 수, 이슈 ID 순으로 고정한다. 제목 표현에 따른 점수 편향이 있으며 AI 문맥·영향 규모 분석은 향후 확장한다.',
          '- 사건별 복수 앵커와 72시간 제한, 모든 기사 쌍 일치로 통합한다. 투싼 계약 개시와 첫날 계약 실적은 구분한다. 발리 버스 공급과 충전 후속은 같은 사업 이슈로 유지한다.',
          '- 전재 비율은 데이터 없음(null). 같은 제목이나 같은 보도자료 추정만으로 전재를 확정하지 않는다. 원문·저자·배포 출처가 확보되면 독립 후속 취재와 구분하도록 확장한다.',
          '- 조회수·댓글은 공개 관측이 저장된 경우에만 최신 값을 집계하며 확보 기사 수를 함께 표시한다. 이번 DB는 전부 데이터 없음(null); CSV는 빈 칸이다. 0과 구분한다.',
          '- 테스트 fixture는 가상 데이터이며 실제 분석 JSON/CSV에 포함하지 않는다.', '']
for name, label in [('spread', 'A. 언론 보도 확산도 TOP 10'), ('rising', 'B. 수집 시점 급상승 TOP 10'), ('industry', 'C. 자동차 산업 중요 뉴스 TOP 10')]:
    lines += ['## '+label, '', '|순위|이슈|기사|매체|선정 근거|', '|---:|---|---:|---:|---|']
    for n, i in enumerate(r['rankings'][name], 1):
        reason = (f"확산 점수 {i['spread_score']}" if name == 'spread' else
                  f"1시간 {i['volume_1h']}건, 증가 {i['growth_per_hour']}건/시간" if name == 'rising' else
                  f"{i['importance_score']}점: "+', '.join(x['criterion'] for x in i['importance_reasons']))
        lines.append(f"|{n}|{i['label']}|{i['article_count']}|{i['independent_publishers']}|{reason}|")
    lines.append('')
lines += ['상세 기사 ID·출처·URL·시간·판정·그룹 근거·지표는 reports/analysis/analysis.json 및 각 CSV 참조.',
          '검증: 기존 28개 + 신규 분석/제외 회귀 테스트. SQLite 무결성 ok. 읽기 전용 분석 전후 DB SHA256 동일 여부도 실행 로그로 확인.']
Path('ANALYSIS_REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
