"""Scheduled collection, briefing and alert candidates. External sending is separate."""
import argparse
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3

from .analysis import analyze, timestamp
from .backup import backup
from .locking import collector_lock
from .multi import collect_publishers, load_sources
from .multi_storage import MultiStorage
from .retention import migrate, prune
from .schedule import KST, slots


def state(db, key, default=None):
    row = db.execute('SELECT value FROM operation_state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(db, key, value):
    db.execute('INSERT OR REPLACE INTO operation_state VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))


def enrich(report, at):
    """Metric windows and title similarity evidence; never asserted as syndication."""
    for issue in report['issues']:
        dated = [(a, timestamp(a['published_at'])) for a in issue['articles']]
        recent = [a for a, t in dated if t and 0 <= (at-t).total_seconds() < 10800]
        previous = sum(t is not None and 10800 <= (at-t).total_seconds() < 21600 for _, t in dated)
        issue['publishers_3h'] = len({a['publisher'] for a in recent})
        issue['previous_3h'] = previous
        issue['growth_ratio_3h'] = len(recent)/previous if previous else None
        issue['growth_status'] = 'new_or_no_baseline' if not previous else 'measured'
        issue['timeliness_hours'] = min(((at-t).total_seconds()/3600 for _, t in dated if t and t <= at), default=None)
        pairs = [(a, b) for n, a in enumerate(issue['articles']) for b in issue['articles'][n+1:]]
        from difflib import SequenceMatcher
        from .rss import normalized_title
        similar = sum(SequenceMatcher(None, normalized_title(a['title']), normalized_title(b['title'])).ratio() >= .85 for a, b in pairs)
        issue['similar_title_pair_ratio'] = similar/len(pairs) if pairs else None
        issue['similarity_basis'] = '제목 유사도 0.85 이상 기사 쌍 비율; 전재율과 다름'
        issue['hourly_volumes'] = [sum(t is not None and h <= (at-t).total_seconds()/3600 < h+1 for _, t in dated) for h in range(24)]
    return report


def track(db, report, at):
    """Reuse an issue ID when retained articles overlap; never use broad topic labels."""
    used = set()
    for issue in report['issues']:
        ids = [a['id'] for a in issue['articles']]
        marks = ','.join('?' for _ in ids)
        candidates = db.execute(f'SELECT issue_id,count(*) n FROM issue_articles WHERE article_id IN ({marks}) GROUP BY issue_id ORDER BY n DESC,issue_id', ids).fetchall()
        stable = next((row[0] for row in candidates if row[0] not in used), issue['id'])
        used.add(stable)
        issue['id'] = stable
        db.execute('INSERT OR IGNORE INTO issues VALUES(?,?,?)', (stable, issue['label'], at.isoformat()))
        db.execute('DELETE FROM issue_articles WHERE issue_id=?', (stable,))
        db.executemany('INSERT OR REPLACE INTO issue_articles VALUES(?,?,?,?)', [(stable, aid, issue['grouping_basis'], at.isoformat()) for aid in ids])
    if used:
        marks=','.join('?' for _ in used)
        db.execute(f'DELETE FROM issue_articles WHERE issue_id NOT IN ({marks})', list(used))
    else:
        db.execute('DELETE FROM issue_articles')
    # Rankings refer to same objects as issues, so IDs stay in sync.


def alerts(db, issues, at, verified_facts=None):
    created = []
    for issue in issues:
        reasons = []
        if issue['publishers_3h'] >= 5:
            reasons.append('최근 3시간 서로 다른 매체 5곳 이상')
        if issue['volume_3h'] >= 5 and issue['previous_3h'] >= 2 and issue['growth_ratio_3h'] >= 2:
            reasons.append('최근 3시간 5건 이상·직전 3시간 2건 이상·2배 증가')
        recent_titles = [a['title'] for a in issue['articles'] if timestamp(a['published_at']) and 0 <= (at-timestamp(a['published_at'])).total_seconds() < 10800]
        serious = sorted(t for t in recent_titles if re.search(r'대규모.*리콜|리콜.*(?:만\s*대|전면)|생산\s*(?:중단|중지)|공장.*가동\s*중단|(?:정책|규제).*(?:시행|발표|변경|강화)|보조금.*(?:삭감|폐지)', t))
        if serious:
            reasons.append('중대 산업 사건 제목 규칙: 편집 검토 필요')
        if not reasons:
            continue
        # Only an explicit editorially verified fact can bypass cooldown.
        # New titles alone are not verified new facts.
        fact = (verified_facts or {}).get(issue['id'])
        facts = 'verified:'+str(fact) if fact else hashlib.sha256('\n'.join(serious).encode()).hexdigest()
        last = db.execute('SELECT created_at,facts_hash FROM alert_candidates WHERE issue_id=? ORDER BY created_at DESC LIMIT 1', (issue['id'],)).fetchone()
        if last and (at-timestamp(last[0])).total_seconds() < 10800 and not (fact and facts != last[1]):
            continue
        db.execute('INSERT INTO alert_candidates(issue_id,created_at,facts_hash,reasons) VALUES(?,?,?,?)',
                   (issue['id'], at.isoformat(), facts, json.dumps(reasons, ensure_ascii=False)))
        created.append(issue['id'])
    return created


def briefing(db, report, kind, scheduled, at, last_collection):
    if scheduled > at:
        return None
    if kind == 'am' and scheduled.astimezone(KST).weekday() >= 5:
        return None
    slot = scheduled.isoformat()+':'+kind
    if db.execute('SELECT 1 FROM briefings WHERE slot=?', (slot,)).fetchone():
        return None
    local = scheduled.astimezone(KST)
    start = local.replace(hour=17 if kind == 'am' else 0, minute=0, second=0, microsecond=0)
    if kind == 'am':
        start -= timedelta(days=1)
    current = [i for i in report['issues'] if any(timestamp(a['published_at']) and start <= timestamp(a['published_at']) <= at for a in i['articles'])]
    prior_date = (local-timedelta(days=1)).date().isoformat()
    prior = state(db, 'baseline:'+prior_date, {})
    prior_counts = prior.get('counts', {})
    changes = [dict(issue_id=i['id'], label=i['label'], new=i['id'] not in prior_counts,
                    article_delta=i['article_count']-prior_counts.get(i['id'], 0),
                    comparison='전일 체크포인트' if prior else '전일 기준 데이터 없음') for i in current]
    ranking_ids = {}
    for name,key in [('spread','spread_score'),('rising','rising_score'),('industry','importance_score')]:
        pool = [i for i in current if i['volume_1h'] and i['growth_per_hour']>0] if name=='rising' else current
        ranking_ids[name]=[i['id'] for i in sorted(pool,key=lambda i:(-i[key],-i['independent_publishers'],-i['article_count'],i['id']))[:10]]
    ranking_ids['major'] = [i['id'] for i in sorted(current, key=lambda i: (-i['importance_score'], -i['volume_24h'], -i['independent_publishers'], i['id']))[:10]]
    # Briefings store links and labels only, and expire when any referenced article expires.
    deadlines = [(timestamp(a['published_at']) or timestamp(a['first_collected_at']))+timedelta(hours=168) for i in current for a in i['articles']]
    payload = dict(kind=kind, scheduled_at=scheduled.isoformat(), generated_at=at.isoformat(),
                   window_start=start.isoformat(), last_collection_at=last_collection,
                   delayed_minutes=max(0, (at-scheduled).total_seconds()/60),
                   expires_at=min(deadlines+[at+timedelta(hours=168)]).isoformat(),
                   rankings=ranking_ids,
                   coverage_lists={status:[i['id'] for i in sorted(current,key=lambda i:(-i['importance_score'],i['id'])) if i.get('carmgz',{}).get('status')==status][:10] for status in ('미보도','후속 보도 검토')},
                   entries={i['id']:dict(label=i['label'],article_count=i['article_count'],publishers=i['independent_publishers'],carmgz=i.get('carmgz')) for i in current},
                   changes=changes,
                   follow_up=[dict(issue_id=i['id'], reason='원문·정책/안전 영향 확인 필요') for i in current if i['importance_score'] >= 25])
    db.execute('INSERT INTO briefings VALUES(?,?,?,?)', (slot, kind, at.isoformat(), json.dumps(payload, ensure_ascii=False)))
    return payload


def public_payload(db, report, at, data_kind='real_rss'):
    # No raw DB, article body, stack trace or request evidence is published.
    articles = []
    for a in report['articles']:
        if a['classification'] != 'relevant':
            continue
        words = [r[0] for r in db.execute('SELECT keyword FROM article_keywords WHERE article_id=?', (a['id'],))]
        articles.append({**{k: a[k] for k in ('id','title','publisher','published_at','url','first_collected_at')}, 'keywords': words})
    public_fields = set('id label article_count independent_publishers publishers independence_basis first_published_at volume_1h volume_3h volume_24h growth_per_hour syndication_ratio syndication_status views comments importance_score importance_reasons spread_score rising_score grouping_basis views_coverage comments_coverage publishers_3h previous_3h growth_ratio_3h growth_status timeliness_hours similar_title_pair_ratio similarity_basis hourly_volumes carmgz'.split())
    issues = [{k: v for k,v in i.items() if k in public_fields} | {'article_ids': [a['id'] for a in i['articles']]} for i in report['issues']]
    rankings = {k: [i['id'] for i in v] for k,v in report['rankings'].items()}
    today = at.astimezone(KST).date()
    major = [i for i in report['issues'] if any(timestamp(a['published_at']) and timestamp(a['published_at']).astimezone(KST).date() == today for a in i['articles'])]
    rankings['major'] = [i['id'] for i in sorted(major, key=lambda i: (-i['importance_score'], -i['volume_24h'], -i['independent_publishers'], i['id']))[:10]]
    return dict(data_kind=data_kind, generated_at=at.isoformat(), expires_at=(at+timedelta(hours=6)).isoformat(),
                last_collection_at=state(db, 'last_collection_at'), last_attempt_at=state(db, 'last_attempt_at'),
                catchup=state(db, 'catchup'), retention_hours=168,
                articles=articles, issues=issues, rankings=rankings, publishers=report['publishers'],
                briefings=[json.loads(r[0]) for r in db.execute('SELECT payload FROM briefings ORDER BY generated_at DESC')],
                alerts=[dict(issue_id=r[0], created_at=r[1], reasons=json.loads(r[2]), delivery_status=r[3]) for r in db.execute('SELECT issue_id,created_at,reasons,delivery_status FROM alert_candidates ORDER BY created_at DESC')],
                errors=[dict(created_at=r[0], phase=r[1], message='운영 오류 기록됨. 상세 원인은 내부 실행 로그에서 확인') for r in db.execute('SELECT created_at,phase,message FROM operation_errors ORDER BY created_at DESC LIMIT 30')])


def run(cfg, database, sources, output, mode='scheduled', at=None, client_factory=None, coverage_checker=None):
    at = at or datetime.now(timezone.utc)
    # A separate outer lock covers retention, collection, briefings and snapshot generation.
    with collector_lock(str(database)+'.operations'):
        store = MultiStorage(database)
        migrate(store.db)
        prune(store.db, at)
        since = timestamp(state(store.db, 'last_tick')) or at-timedelta(hours=24)
        due = slots(max(since, at-timedelta(hours=24)), at)
        due_briefs = [(t,k) for t,k in due if k in ('am','pm')]
        # No synthetic historical catchup briefings: latest missed slot of each kind only.
        due_briefs = [next((x for x in reversed(due_briefs) if x[1] == k), None) for k in ('am','pm')]
        if mode in ('am','pm'):
            due_briefs = [(at, mode)]
        should_collect = mode != 'refresh'
        old_success = state(store.db, 'last_collection_at')
        previous_run=store.db.execute('SELECT coalesce(max(id),0) FROM runs').fetchone()[0]
        with store.db:
            put(store.db, 'catchup', dict(since=old_success, horizon_hours=168,
                 limitation='현재 RSS가 제공하는 최근 7일 항목만 보충. 피드에서 사라진 누락분 복구는 보장하지 않음'))
        store.close()
        if should_collect:
            try:
                with redirect_stdout(io.StringIO()):
                    kwargs = {'client_factory':client_factory} if client_factory else {}
                    collect_publishers(dict(cfg, lookback_days=7, retention_policy=True,
                                            timeout_seconds=min(cfg.get('timeout_seconds',8),8),
                                            retries=0,max_run_seconds=480), database, sources, **kwargs)
            except Exception as exc:
                with closing(sqlite3.connect(database)) as db:
                    with db:
                        db.execute('INSERT INTO operation_errors(created_at,phase,message) VALUES(?,?,?)', (at.isoformat(), 'collect', type(exc).__name__))
        finished = datetime.now(timezone.utc) if client_factory is None and should_collect else at
        store = MultiStorage(database)
        db = store.db
        try:
            with db:
                if should_collect:
                    put(db, 'last_attempt_at', finished.isoformat())
                    checks = db.execute('SELECT status FROM feed_checks WHERE run_id=(SELECT max(run_id) FROM feed_checks) AND run_id>?', (previous_run,)).fetchall()
                    if any(r[0] in ('collected','empty_feed') for r in checks):
                        put(db, 'last_collection_at', finished.isoformat())
                    for publisher, error in db.execute("SELECT publisher_id,error FROM feed_checks WHERE run_id=(SELECT max(run_id) FROM feed_checks) AND status='failed'"):
                        db.execute('INSERT INTO operation_errors(created_at,phase,message) VALUES(?,?,?)', (finished.isoformat(), 'rss:'+publisher, error or 'failed'))
            prune(db, finished)
            report = enrich(analyze(database, sources, finished), finished)
            with db:
                track(db, report, finished)
                # Check after stable issue IDs, before briefing snapshots. Fixture runs stay offline.
                if cfg.get('coverage', True) and (cfg.get('data_kind','real_rss') != 'synthetic_fixture' or coverage_checker):
                    from .coverage import load_config, verify_issues
                    coverage_config = load_config(cfg.get('coverage_config','coverage.json'))
                    if coverage_config.get('enabled'):
                        verify_issues(db, report, finished, coverage_config,
                                      force=any(due_briefs), checker=coverage_checker)
                if should_collect:
                    alerts(db, report['issues'], finished)
                last_collection = state(db, 'last_collection_at')
                for item in due_briefs:
                    if item:
                        briefing(db, report, item[1], item[0], finished, last_collection)
                put(db, 'baseline:'+finished.astimezone(KST).date().isoformat(),
                    dict(at=finished.isoformat(), counts={i['id']:i['article_count'] for i in report['issues']}))
                put(db, 'last_tick', finished.isoformat())
            prune(db, finished)
            payload = public_payload(db, report, finished, cfg.get('data_kind','real_rss'))
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            for asset in Path('web').iterdir():
                if asset.is_file():
                    shutil.copyfile(asset, target/asset.name)
            serialized=json.dumps(payload, ensure_ascii=False, separators=(',',':'))
            if len(serialized.encode('utf-8'))>10_000_000:
                raise RuntimeError('Dashboard JSON exceeds 10 MB storage budget')
            temporary=target/'dashboard.json.tmp'
            temporary.write_text(serialized,encoding='utf-8')
            temporary.replace(target/'dashboard.json')
            return payload
        finally:
            store.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='config.json')
    p.add_argument('--database', default='data/news.sqlite3')
    p.add_argument('--output', default='site')
    p.add_argument('--mode', choices=['scheduled','collect','am','pm','refresh'], default='scheduled')
    p.add_argument('--backup-existing', action='store_true', help='One-time pre-operation verified local backup')
    args = p.parse_args()
    if Path(args.database).exists():
        with closing(sqlite3.connect(Path(args.database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            initialized = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_state'").fetchone()
        if args.backup_existing or not initialized:
            # One-time migration always has a verified backup before the first deletion.
            backup(args.database, str(args.database)+'.pre-operations-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    try:
        payload = run(cfg, args.database, load_sources(cfg.get('publishers','publishers.json')), args.output, args.mode)
    except Exception as exc:
        # Persist a sanitized operational error when schema initialization succeeded.
        try:
            with closing(sqlite3.connect(Path(args.database).resolve().as_uri()+'?mode=rw',uri=True)) as db:
                with db:
                    db.execute('INSERT INTO operation_errors(created_at,phase,message) VALUES(?,?,?)',
                               (datetime.now(timezone.utc).isoformat(),'operation',type(exc).__name__))
        except sqlite3.Error:
            pass
        raise
    print(json.dumps(dict(articles=len(payload['articles']), issues=len(payload['issues']),
                         briefings=len(payload['briefings']), last_collection_at=payload['last_collection_at']),ensure_ascii=True))


if __name__ == '__main__':
    main()
