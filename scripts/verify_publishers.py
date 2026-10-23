"""Discover official advertised RSS and verify policy + XML. No article DB writes.

Candidates never become ACTIVE from a URL guess or HTTP 200 alone.
Run from repository root: python -m scripts.verify_publishers --promote
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import time
from pathlib import Path
from urllib.parse import urljoin

from carmgz.policy_http import PolicyClient
from carmgz.rss import PublisherRSS, matching_keywords


class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.feeds = []; self.guides = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link' and 'rss' in a.get('type', '').lower():
            self.feeds.append(a.get('href', ''))
        if tag == 'a' and 'rss' in a.get('href', '').lower():
            self.guides.append(a['href'])


def verify(source, keywords):
    result = dict(id=source['id'], checked_at=datetime.now(timezone.utc).isoformat(),
                  status='PENDING', feed_url=source.get('feed_url'), fetched=0,
                  relevant=0, parsed=False, error=None, http_status=None)
    if source['status'] == 'EXCLUDED':
        return dict(result, status='EXCLUDED')
    if source.get('permission') == 'contract_required':
        return dict(result, status='UNSUPPORTED',error=source.get('alternative','사전 계약 필요: 요청하지 않음'),policy='permission_required')
    client = PolicyClient(2, 8, 0)
    deadline = time.monotonic()+45
    original_sleep = client.sleep
    def bounded_sleep(seconds):
        if time.monotonic()+seconds > deadline:
            raise TimeoutError('검증 시간 예산 초과; robots 대기 시간을 우회하지 않고 보류')
        original_sleep(seconds)
    client.sleep = bounded_sleep
    try:
        documented = source.get('rss_status') in ('official_documented', 'official_advertised_verified')
        if not documented or not source.get('feed_url'):
            home = source['homepage']
            parser = Links(); parser.feed('')
            body = client.fetch(home)
            parser.feed(body.decode('utf-8', errors='replace'))
            result['homepage_http_status'] = client.last_status
            # Follow at most one official RSS guide, never invent an RSS URL.
            if not parser.feeds and parser.guides:
                guide = urljoin(home, parser.guides[0])
                guide_parser = Links()
                guide_parser.feed(client.fetch(guide).decode('utf-8', errors='replace'))
                parser = guide_parser
                home = guide
            if not parser.feeds:
                result.update(error='공식 페이지에서 검증 가능한 RSS alternate 미확보', status='UNSUPPORTED')
                return result
            result.update(feed_url=urljoin(home, parser.feeds[0]), address_source=home)
        else:
            result['address_source'] = source['official_reference']
        body = client.fetch(result['feed_url'])
        result['http_status'] = client.last_status
        articles = PublisherRSS(dict(source, feed_url=result['feed_url'])).parse(body)
        result.update(status='ACTIVE', parsed=True, fetched=len(articles),
                      relevant=sum(bool(matching_keywords(a, keywords)) for a in articles),
                      dated=sum(a.published_at is not None for a in articles))
    except Exception as exc:
        result.update(status='ERROR', error=str(exc), http_status=client.last_status)
    finally:
        result['policy'] = client.policy_result
        result['requests'] = client.evidence
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--promote', action='store_true')
    p.add_argument('--output', default='logs/publisher-verification.json')
    args = p.parse_args()
    path = Path('publishers.json')
    sources = json.loads(path.read_text(encoding='utf-8'))
    keywords = json.loads(Path('config.json').read_text(encoding='utf-8-sig'))['keywords']
    # Six independent origins at once; each client respects per-origin robots delays.
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    completed = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(verify,s,keywords):s['id'] for s in sources}
        for job in as_completed(jobs):
            result = job.result(); completed[result['id']] = result
            # Persist completed evidence even if a later site times out.
            Path(args.output).write_text(json.dumps(list(completed.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    results = [completed[s['id']] for s in sources]
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.promote:
        for source, result in zip(sources, results):
            source['status'] = result['status']
            source['verification'] = {k: result.get(k) for k in ('checked_at','status','http_status','parsed','error','address_source','policy')}
            # ERROR does not erase an existing route. Next collection may recover.
            if result['status'] == 'ACTIVE':
                source.update(feed_url=result['feed_url'], enabled=True,
                              rss_status='official_advertised_verified',
                              permission='public_feed_policy_check')
                source['official_reference'] = result['address_source']
            elif source.get('rss_status') == 'candidate_unverified':
                source.update(enabled=False, permission='not_confirmed')
        path.write_text(json.dumps(sources, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    from collections import Counter
    print(json.dumps(dict(Counter(r['status'] for r in results)), ensure_ascii=True))


if __name__ == '__main__':
    main()
