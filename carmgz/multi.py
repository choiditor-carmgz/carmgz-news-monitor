"""Multi-publisher collection and reproducible verification report."""
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .locking import collector_lock
from .policy_http import PolicyClient
from .rss import PublisherRSS, matching_keywords
from .multi_storage import MultiStorage
from .storage import now


def load_sources(path):
    sources=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    ids=set()
    for s in sources:
        if not s.get('id') or s['id'] in ids or not s.get('publisher'):
            raise ValueError('Publisher IDs must be unique and names required')
        ids.add(s['id'])
        if s.get('enabled') and not s.get('feed_url'):
            raise ValueError('Enabled publisher requires feed_url')
        if s.get('enabled') and s.get('permission') in ('contract_required','not_confirmed'):
            raise ValueError('Publisher collection permission is not confirmed')
    return sources


def collect_publishers(cfg,db_path,sources,report_path=None,client_factory=PolicyClient):
    with collector_lock(db_path):
        store=MultiStorage(db_path)
        try:
            store.register(sources)
            run=store.start(cfg)
            results=[]
            deadline=time.monotonic()+cfg.get('max_run_seconds',float('inf'))
            # Oldest actual request first: newly added feeds and budget-deferred feeds
            # cannot be perpetually starved by the first publishers in the registry.
            attempted=dict(store.db.execute("SELECT publisher_id,max(checked_at) FROM feed_checks WHERE status IN ('collected','empty_feed','stale_feed','failed') GROUP BY publisher_id"))
            for source in sorted(sources,key=lambda s:attempted.get(s['id'],'')):
                result=dict(id=source['id'],publisher=source['publisher'],feed_url=source.get('feed_url'),
                    rss_status=source['rss_status'],permission=source['permission'],status='not_verified',
                    http_status=None,policy='not_checked',parsed=False,fetched=0,relevant=0,inserted=0,error=None,requests=[])
                from .analysis import EXCLUDED_IDS, EXCLUDED_NAMES
                if source['id'] in EXCLUDED_IDS or source['publisher'] in EXCLUDED_NAMES:
                    result['status']='excluded'
                    result['error']='사용자 지정 수집·분석 제외 매체'
                elif not source.get('enabled'):
                    result['status']='held' if source.get('feed_url') else 'no_confirmed_feed'
                    result['error']=source.get('alternative') or '이용 조건 검토/허가 필요; RSS 요청하지 않음'
                elif time.monotonic() >= deadline:
                    result['status']='deferred_budget'
                    result['error']='이번 실행 요청 시간 예산 초과: 다음 실행에서 재시도'
                else:
                    client=client_factory(cfg['interval_seconds'],cfg['timeout_seconds'],cfg['retries'])
                    if cfg.get('max_run_seconds') and hasattr(client,'sleep'):
                        original_sleep=client.sleep
                        def budget_sleep(seconds, sleeper=original_sleep):
                            if time.monotonic()+seconds>=deadline:
                                raise RuntimeError('Request budget exceeded; defer without ignoring crawl delay')
                            sleeper(seconds)
                        client.sleep=budget_sleep
                    try:
                        articles=PublisherRSS(source).parse(client.fetch(source['feed_url']))
                        result.update(parsed=True,fetched=len(articles))
                        cutoff=datetime.now(timezone.utc)-timedelta(days=cfg.get('lookback_days',7))
                        recent=[a for a in articles if a.published_at is None or datetime.fromisoformat(a.published_at)>=cutoff]
                        if cfg.get('retention_policy'):
                            # Unknown dates cannot safely be re-imported after expiry.
                            result['unknown_date_skipped']=sum(a.published_at is None for a in recent)
                            upper=datetime.now(timezone.utc)
                            recent=[a for a in recent if a.published_at is not None and datetime.fromisoformat(a.published_at)<=upper]
                        result['outside_lookback']=len(articles)-len(recent)
                        relevant=[a for a in recent if matching_keywords(a,cfg['keywords'])]
                        result['relevant']=len(relevant)
                        result['inserted']=store.save_articles(run,source,relevant,cfg['keywords'])
                        result['status']=('stale_feed' if articles and not recent else 'collected' if articles else 'empty_feed')
                    except Exception as exc:
                        result['status']='failed'
                        result['error']=f'{type(exc).__name__}: {exc}'
                        store.record(run,source['id'],source['id'],error=result['error'])
                    result['requests']=client.evidence
                    # Only a feed response is reported here; robots status stays in request evidence.
                    result['policy']=client.policy_result if client.policy_result!='not_checked' else 'unavailable'
                    feed_requests=[x for x in client.evidence if x.get('phase')=='feed']
                    result['http_status']=feed_requests[-1]['status'] if feed_requests else None
                store.check(run,source,result)
                results.append(result)
                # Console streams may use cp1252/ASCII; files below remain UTF-8.
                print(json.dumps(result,ensure_ascii=True),flush=True)
            summary=store.finish(run)
            report=dict(checked_at=now(),run_id=run,summary=summary,publishers=results)
            if report_path:
                Path(report_path).parent.mkdir(parents=True,exist_ok=True)
                Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            return summary
        finally:
            store.close()
