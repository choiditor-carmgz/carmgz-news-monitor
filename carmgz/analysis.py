"""Read-only, deterministic RSS evidence analysis. No network or DB mutations."""
import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

EXCLUDED_IDS = {'motorgraph', 'toprider', 'carguy', 'autoview'}
EXCLUDED_NAMES = {'모터그래프', '탑라이더', '카가이', '오토뷰'}

# Each event needs multiple concrete anchors, never a title similarity threshold.
EVENTS = [
    ('winter-evo4', '한국타이어 윈터 아이셉트 에보4 독일 평가', [r'한국타이어', r'윈터\s*아이셉트\s*에보\s*4', r'독일|獨', r'1위']),
    ('bali-bus', '발리 전기버스 공급·충전 사업', [r'발리', r'전기버스|카운티']),
    ('gm-autonomy', 'GM 자율주행 확대 로드맵', [r'GM|제너럴 모터스|캐딜락', r'자율주행']),
    ('pbv-dealers', '기아 글로벌 PBV 딜러 초청', [r'기아', r'PBV', r'딜러', r'초청|집결']),
    ('ev6-test', '기아 EV6 GT 독일 비교평가', [r'EV6', r'GT', r'평가', r'1위']),
    ('tucson-orders', '신형 투싼 첫날 계약 실적', [r'투싼', r'첫날', r'계약']),
    ('tucson-launch', '신형 투싼 계약 개시', [r'투싼', r'계약', r'개시', r'3140']),
    ('parking-ai', '카카오모빌리티 AI 주차 기술', [r'카카오모빌리티', r'주차', r'AI']),
    ('tech-campus', '현대차 미래차 특성화고 교육 지원', [r'현대차', r'특성화고']),
    ('police-cars', '기아 국제치안산업대전', [r'기아', r'치안산업대전']),
    ('forest', '현대차 이포레스트 테크데이', [r'현대차', r'이포레스트']),
    ('truck-l4', '현대차 레벨4 대형트럭 실증', [r'현대차', r'레벨 ?4', r'트럭', r'실증']),
    ('ideas', '현대차 아이디어 페스티벌', [r'현대차', r'아이디어 페스티벌']),
    ('school-bus', '현대차 인도네시아 교육 지원', [r'현대차', r'인니|인도네시아', r'교육']),
    ('cheonggye', '청계천 야간 자율주행버스', [r'청계천', r'자율주행', r'야경|야간']),
]


def timestamp(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def classify(article):
    from .relevance import HUNGER, automotive_terms
    if article['publisher'] in EXCLUDED_NAMES:
        return 'excluded', '사용자 지정 제외 매체'
    title = article['title'] or ''
    if HUNGER.search(title):
        return 'irrelevant', '기아 자동차와 동음이의어인 구호단체'
    from .editorial import context, facts
    contextual = context(title)
    if contextual:
        return contextual
    if re.search(r'정몽구\s*재단',title) and not re.search(r'자동차\s*(?:기술|산업|안전)|미래차|전기차|자율주행',title):
        return 'review', '완성차 재단 사회공헌: 자동차 산업과의 직접 연결 확인 필요'
    if re.search(r'바둑로봇|건설작업로봇|주강로보테크|빅웨이브로보틱스|한일,', title):
        return 'review', '일반 로봇·협력 기사: 자동차 연결 근거 부족'
    if '컨선' in title:
        return 'review', '배터리 선박: 자동차 중심 범위 재검토 필요'
    if automotive_terms(title):
        return 'relevant', 'RSS 제목에 자동차·이동수단·핵심 전지 기술 근거'
    if facts(title)['entities'] and facts(title)['actions']:
        return 'relevant', '자동차·부품·전지 기업과 구체 산업 사건 제목 근거'
    if re.search(r'완성차|승용차|수입차|차량|부품업체|이차전지|전고체|로보택시|車',title) and facts(title)['actions']:
        return 'relevant', '차량·완성차·핵심 전지 산업 문맥과 구체 사건 제목 근거'
    return 'review', '제목만으로 관련성 확정 불가'


def same_event(a, b):
    da, db = timestamp(a['published_at']), timestamp(b['published_at'])
    if not da or not db or abs((da-db).total_seconds()) > 72*3600:
        return None
    from .editorial import facts
    left,right=facts(a['title']),facts(b['title'])
    if left['years'] and right['years'] and not set(left['years']) & set(right['years']):
        return None
    if all(re.search(r'공급|투입',x['title']) for x in (a,b)):
        counts=[{v for unit,v in p['quantities'] if unit=='대'} for p in (left,right)]
        if all(counts) and not counts[0] & counts[1]:
            return None
    # Materially different actions or explicit locations/numbers veto broad anchors.
    for facet in (r'리콜|결함', r'사망|사고', r'생산\s*중단', r'화재'):
        if bool(re.search(facet, a['title'])) != bool(re.search(facet, b['title'])):
            return None
    for pattern in (r'(\d+)\s*대\s*공급', r'(20\d{2})년'):
        left, right = set(re.findall(pattern,a['title'])), set(re.findall(pattern,b['title']))
        if left and right and left != right:
            return None
    for key, label, anchors in EVENTS:
        if all(re.search(p, a['title'], re.I) and re.search(p, b['title'], re.I) for p in anchors):
            # Conflicting explicit quantities/years can identify different events.
            years = [set(re.findall(r'20\d{2}년', x['title'])) for x in (a, b)]
            if all(years) and years[0] != years[1]:
                return None
            return key, label
    from .editorial import related_event
    matched = related_event(a['title'],b['title'])
    if matched:
        return matched[0], min(a['title'],b['title'])
    return None


def build_issues(articles, as_of):
    groups = []
    for article in sorted(articles, key=lambda a: a['id']):
        group = next((g for g in groups if all(same_event(article, x) for x in g)), None)
        if group is None:
            groups.append([article])
        else:
            group.append(article)
    issues = []
    for group in groups:
        event = same_event(*group[:2]) if len(group) > 1 else None
        times = [timestamp(a['published_at']) for a in group]
        times = [t for t in times if t and t <= as_of]
        count = lambda lo, hi: sum(lo <= (as_of-t).total_seconds()/3600 < hi for t in times)
        n1, n3, n24 = count(0, 1), count(0, 3), count(0, 24)
        growth = n1-count(1, 3)/2
        publishers = sorted({a['publisher'] for a in group})
        issues.append(dict(id=hashlib.sha256('|'.join(sorted(a['id'] for a in group)).encode()).hexdigest()[:16],
            label=event[1] if event else group[0]['title'], articles=group,
            article_count=len(group), independent_publishers=len(publishers), publishers=publishers,
            independence_basis='서로 다른 등록 매체 수; 소유관계·자체취재 독립성 미검증',
            first_published_at=min(times).isoformat() if times else None,
            volume_1h=n1, volume_3h=n3, volume_24h=n24, growth_per_hour=growth,
            syndication_ratio=None, syndication_status='본문·배포 출처 미확보: 전재/독립 후속취재 미확인',
            views=None, comments=None,
            importance_score=0, importance_reasons=[],
            spread_score=len(publishers)*10+len(group),
            rising_score=max(0, growth)*3+n1,
            grouping_basis='사건별 복수 앵커 + 72시간 + 그룹 전체 쌍 검증' if event else '병합 근거 부족: 단독 이슈'))
    from .editorial import score
    for issue in issues:
        score(issue,as_of)
    return issues


def analyze(database, sources, as_of):
    uri = Path(database).resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        articles = [dict(r) for r in db.execute('SELECT * FROM articles ORDER BY id')]
        checks = [dict(r) for r in db.execute('SELECT * FROM feed_checks WHERE run_id=(SELECT max(run_id) FROM feed_checks)')]
        latest_row = db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
        latest = dict(latest_row) if latest_row else {'id':None, 'started_at':as_of.isoformat()}
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        metrics = [dict(r) for r in db.execute('SELECT * FROM article_metrics')]
        successes = dict(db.execute("SELECT publisher_id,max(checked_at) FROM feed_checks WHERE parsed=1 GROUP BY publisher_id"))
    for a in articles:
        canonical = next((s['publisher'] for s in sources if a['publisher'] in s.get('aliases',[])), None)
        if canonical:
            a['original_publisher'] = a['publisher']
            a['publisher'] = canonical
        a['classification'], a['classification_reason'] = classify(a)
        a['missing_fields'] = [k for k in ('publisher', 'title', 'published_at', 'url') if not a[k]]
        a['invalid_date'] = bool(a['published_at'] and not timestamp(a['published_at']))
        a['invalid_url'] = urlsplit(a['url']).scheme not in ('http', 'https') or not urlsplit(a['url']).netloc
    eligible = [a for a in articles if a['classification'] == 'relevant' and
                (timestamp(a['published_at']) is None or 0 <= (as_of-timestamp(a['published_at'])).total_seconds() < 168*3600)]
    issues = build_issues(eligible, as_of)
    # Most recent public observations per article, per field; missing values stay null.
    for issue in issues:
        for field in ('views', 'comments'):
            values = []
            for a in issue['articles']:
                candidates = [m for m in metrics if m['article_id'] == a['id'] and m[field] is not None
                              and timestamp(m['observed_at']) and timestamp(m['observed_at']) <= as_of
                              and m[field] >= 0]
                values.append(max(candidates, key=lambda m: timestamp(m['observed_at']))[field] if candidates else None)
            issue[field] = sum(v for v in values if v is not None) if any(v is not None for v in values) else None
            issue[field+'_coverage'] = sum(v is not None for v in values)
    by_id = {c['publisher_id']: c for c in checks}
    publishers = []
    for s in sources:
        c = by_id.get(s['id'], {})
        publishers.append(dict(id=s['id'], publisher=s['publisher'],
            category=s.get('category'),homepage=s.get('homepage'),feed_url=s.get('feed_url'),
            address_source=s.get('official_reference'),registry_status=s.get('status','PENDING'),
            last_success_at=successes.get(s['id']),
            collection_state=('EXCLUDED' if s['id'] in EXCLUDED_IDS else
                'ACTIVE' if c.get('parsed') else 'ERROR' if c.get('status')=='failed' else
                'UNSUPPORTED' if s.get('status')=='UNSUPPORTED' else 'PENDING'),
            excluded=s['id'] in EXCLUDED_IDS or s['publisher'] in EXCLUDED_NAMES,
            stored=sum(a['publisher'] == s['publisher'] for a in articles),
            checked_at=c.get('checked_at'),
            status=c.get('status', 'not_verified'), rss_items=c.get('fetched'),
            keyword_candidates=c.get('relevant'), error=c.get('error')))
    rankings = {}
    for name, key in [('spread', 'spread_score'), ('rising', 'rising_score'), ('industry', 'importance_score')]:
        pool = [i for i in issues if i['volume_1h'] and i['growth_per_hour'] > 0] if name == 'rising' else issues
        rankings[name] = sorted(pool, key=lambda i: (-i[key], -i['independent_publishers'], -i['article_count'], i['id']))[:10]
    from .editorial import rank
    rankings['industry'] = rank(issues)
    rankings['major'] = list(rankings['industry'])
    return dict(data_kind='real_sqlite_rss', as_of=as_of.isoformat(), database_integrity=integrity,
        latest_run=latest['id'], latest_rss_items=sum(c['fetched'] for c in checks),
        latest_keyword_candidates=sum(c['relevant'] for c in checks), stored_articles=len(articles),
        earlier_only=[a['id'] for a in articles if a['last_seen_at'] < latest['started_at']],
        classification_counts=dict(Counter(a['classification'] for a in articles)),
        publishers=publishers, articles=articles, issues=issues, rankings=rankings,
        metric_observations=metrics,
        limitations=['RSS 본문 미저장: 본문·저자·배포 출처 대조는 향후 확장',
            '1,574 RSS 항목 전체 명세 미저장: 미저장 항목 재현·누락 분류 평가 불가',
            'AI 확장: 문맥 이해, 산업 영향 규모, 인과관계, 독립 취재 판정',
            '시간창은 발행 시각 기준. 수집 주기·매체 편향이 있으며 실제 독자 관심도를 의미하지 않음'])


def export(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    datasets = {'articles': report['articles'], 'publishers': report['publishers'], 'issues': report['issues']}
    datasets.update({'top10_'+k: v for k, v in report['rankings'].items()})
    for name, rows in datasets.items():
        with (directory/(name+'.csv')).open('w', encoding='utf-8-sig', newline='') as f:
            fields = list(rows[0]) if rows else ['id']
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', default='data/news.sqlite3')
    p.add_argument('--publishers', default='publishers.json')
    p.add_argument('--as-of', help='Timezone-aware ISO time; default current UTC, never latest article time')
    p.add_argument('--output', default='reports/analysis')
    args = p.parse_args()
    as_of = timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of is None:
        p.error('--as-of requires timezone-aware ISO timestamp')
    sources = json.loads(Path(args.publishers).read_text(encoding='utf-8-sig'))
    export(analyze(args.database, sources, as_of), args.output)


if __name__ == '__main__':
    main()
