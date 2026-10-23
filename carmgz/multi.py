"""Multi-publisher collection and reproducible verification report."""
import json
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
    return sources


def collect_publishers(cfg,db_path,sources,report_path=None,client_factory=PolicyClient):
    with collector_lock(db_path):
        store=MultiStorage(db_path)
        try:
            store.register(sources)
            run=store.start(cfg)
            results=[]
            for source in sources:
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
                else:
                    client=client_factory(cfg['interval_seconds'],cfg['timeout_seconds'],cfg['retries'])
                    try:
                        articles=PublisherRSS(source).parse(client.fetch(source['feed_url']))
                        result.update(parsed=True,fetched=len(articles))
                        cutoff=datetime.now(timezone.utc)-timedelta(days=cfg.get('lookback_days',7))
                        recent=[a for a in articles if a.published_at is None or datetime.fromisoformat(a.published_at)>=cutoff]
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
                print(json.dumps(result,ensure_ascii=False),flush=True)
            summary=store.finish(run)
            report=dict(checked_at=now(),run_id=run,summary=summary,publishers=results)
            if report_path:
                Path(report_path).parent.mkdir(parents=True,exist_ok=True)
                Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            return summary
        finally:
            store.close()
