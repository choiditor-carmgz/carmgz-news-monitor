"""Build a readable verification report from observed feed runs, never inferred success."""
import json
import platform
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

root=Path(__file__).resolve().parents[1]
latest=json.loads((root/'reports/latest.json').read_text(encoding='utf-8'))
sources={s['id']:s for s in json.loads((root/'publishers.json').read_text(encoding='utf-8'))}
rows=latest['publishers']
status=Counter(s['status'] for s in rows)
db=sqlite3.connect(root/'data/news.sqlite3')
checks=db.execute('PRAGMA integrity_check').fetchone()[0]
fk=db.execute('PRAGMA foreign_key_check').fetchall()
total=db.execute('SELECT count(*) FROM articles').fetchone()[0]
publishers=db.execute('SELECT count(DISTINCT publisher) FROM articles').fetchone()[0]
repeat=json.loads((root/'reports/windows-repeat-pass.json').read_text(encoding='utf-8'))
time=datetime.fromisoformat(latest['checked_at']).astimezone(timezone(timedelta(hours=9))).isoformat()
lines=['# 다중 언론사 Windows 실수집 검증', '',f'검증 종료: {time} (Asia/Seoul). Python {platform.python_version()}, {platform.system()} {platform.release()}.', '',
'## 결과', '',f'- 등록 후보: {len(rows)}개. 최종 상태: '+', '.join(f'{k}={v}' for k,v in sorted(status.items()))+'.',
f"- 최종 실행 RSS 파싱 항목: {sum(s['fetched'] for s in rows):,}건. 기간 내 제목 필터 일치: {sum(s['relevant'] for s in rows)}건.",
f"- 최종 실행 저장 통계: 신규 {latest['summary']['inserted']}건, 중복 {latest['summary']['duplicates']}건, 실패 {latest['summary']['errors']}개 피드.",
f'- 누적 실제 저장 기사: {total}건, 저장 기사가 있는 언론사 {publishers}개. 합성 테스트는 임시 DB에서만 실행.',
f"- 동일 구성 반복 검증: 관련 항목 {repeat['summary']['fetched']}건, 신규 {repeat['summary']['inserted']}건, 중복 {repeat['summary']['duplicates']}건.",
f'- SQLite integrity_check={checks}, foreign_key_check 오류 {len(fk)}건. 기존 Google 실패 이력도 보존.',
'- 기존 18개 + 추가 10개 = 28개 테스트 통과. 실제 네트워크 검증과 모의 테스트를 구분함.',
'- DNS가 제한된 샌드박스 실행은 실패했으며, 승인된 Windows 네트워크 실행에서 실수집 검증함.', '',
'collected는 실제 RSS 항목 파싱 성공이며 자동차 관련 항목이 0건일 수도 있습니다. stale_feed는 파싱됐지만 전부 기간 밖인 과거 피드입니다.',
'HTTP —는 피드 응답 미관측입니다. robots 응답 코드로 피드 성공/실패를 꾸미지 않았습니다.',
'정책 allowed는 robots 기준 접근 가능만 의미하며 상업적 이용 허가가 아닙니다. held는 확인한 이용 제한 때문에 요청하지 않았습니다.',
'RSS 미확인은 공식 안내와 허용된 홈페이지 검사에서 주소를 확보하지 못했다는 뜻이며 RSS 부재를 확정하지 않습니다.', '',
'## 언론사별 최종 검증', '',
'| 언론사 | RSS 제공 근거 | 정책 | 피드 HTTP | 파싱 | 전체 항목 | 관련 기사 | 결과 / 실패 원인 |',
'|---|---|---|---:|---|---:|---:|---|']
for s in rows:
    error=(s['error'] or s['status']).replace('|','/').replace('\n',' ')
    lines.append(f"| {s['publisher']} | {s['rss_status']} | {s.get('policy','not_checked')} | {s['http_status'] or '—'} | {'성공' if s['parsed'] else '미성공/미요청'} | {s['fetched']} | {s['relevant']} | {error} |")
lines += ['', '## 피드 주소와 공식 근거', '', '| 언론사 | 최종 후보 피드 | 공식 안내/홈페이지 | 대체 수집 |','|---|---|---|---|']
for s in rows:
    source=sources[s['id']]
    feed=source.get('feed_url')
    lines.append(f"| {source['publisher']} | {('['+feed+']('+feed+')') if feed else '미확인'} | [공식 페이지]({source['official_reference']}) | {source.get('alternative') or 'RSS 메타데이터 / 별도 계약 미확보'} |")
lines += ['', '## 조사 범위와 근거', '',
'- reports/discovery.json: 40개 공식 홈페이지/RSS 안내의 HTTP·정책 결과와 RSS/제휴 안내 링크. 기사 본문 수집 없음.',
'- reports/discovery-supplement.json, reports/discovery-rss-pages.json: 현재 도메인 및 RSS 안내를 추가 조사한 증거.',
'- reports/windows-first-pass.json: 최초 실제 RSS 수집. windows-repeat-pass.json: 반복 중복 검증. windows-expanded-pass.json: 전문지 확장 검증.',
'- reports/latest.json: 최종 구성 실행. data/news.sqlite3의 feed_checks와 query_results에 누적 이력 저장.',
'- 초기 잘못된 후보 URL(서울신문·서울경제·파이낸셜뉴스)은 이전 보고서에 404로 남기고 공식 홈페이지 안내에서 새 주소를 찾아 교체.',
'- 모터트렌드의 과거 도메인 인증서 만료, 오토타임즈의 과거 DNS 실패와 현재 공식 도메인 TLS 오류는 해당 조사 파일에 보존. 인증서 검증 해제하지 않음.',
'- 알려진 이용 제한: [SBS](https://news.sbs.co.kr/news/rss.do), [경향신문](https://www.khan.co.kr/company/sub03_2.html), [이투데이](https://www.etoday.co.kr/rss/).',
'- 공식 대체 수단: [뉴스1 CONNECT](https://connect.news1.kr/) 계약형 공급 서비스. 계약·자동 수집 API 권한 미확보이므로 수집 안 함.',
'- 나머지 RSS 미확인 언론사는 공식 홈페이지 제휴/저작권 문의 경로를 근거 파일에 보존. 명시적으로 허용된 API를 발견하지 못해 임의 크롤링을 추가하지 않음.', '',
'## 데이터 해석 한계', '',
'관련 기사 수는 제목 키워드 필터 결과입니다. 본문/AI 검증을 거친 자동차 기사 확정 수가 아닙니다.',
'서로 다른 언론사의 보도는 별개로 보존하며, 같은 제목 관계도 전재 확정으로 단정하지 않습니다.',
'이슈 연결 테이블은 준비했으나 실제 이슈 분류·독립 취재/전재 판정·AI 분석은 다음 단계입니다.',
'조회수와 댓글 수는 확보하지 못해 기록하지 않았습니다. 대시보드·스케줄러·main 병합은 이번 범위에 포함하지 않았습니다.', '']
(root/'MULTI_SOURCE_VALIDATION.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(dict(status=dict(status),rss_items=sum(s['fetched'] for s in rows),relevant=sum(s['relevant'] for s in rows),summary=latest['summary'],stored=total,publishers=publishers,integrity=checks,foreign_keys=len(fk)),ensure_ascii=True))
db.close()
