"""Opt-in bounded HTTP response study. No DB, article fetch, RSS or deployment."""
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import BaseHandler, getproxies

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carmgz.coverage import load_config, parse_search, search_diagnostics, safe_response_url
from carmgz.policy_http import PolicyClient


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def http_date(value):
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def header_facts(headers):
    """Never serialize arbitrary header values, cookies, credentials or node names."""
    cache = headers.get('Cache-Control', '').lower()
    directives = set(re.findall(r'(?:^|,)\s*([a-z-]+)', cache))
    numeric = lambda v: int(v) if re.fullmatch(r'\d{1,10}', v.strip()) else None
    return dict(age=numeric(headers.get('Age', '')),
        date=http_date(headers.get('Date')), expires=http_date(headers.get('Expires')),
        last_modified=http_date(headers.get('Last-Modified')),
        vary=sorted(set(re.findall(r'[a-z*-]+',headers.get('Vary','').lower())) &
                    {'accept','accept-encoding','user-agent','cookie','authorization','origin','*'}),
        cache_control=sorted(directives & {'no-cache','no-store','public','private',
            'max-age','s-maxage','must-revalidate','proxy-revalidate'}),
        cache_max_age=numeric((re.search(r'(?:^|,)\s*max-age=(\d+)', cache) or ['',''])[1]),
        via_present=bool(headers.get('Via')),
        cache_markers=sorted(set(re.findall(r'[A-Z]+',
            (headers.get('X-Cache','')+' '+headers.get('CF-Cache-Status','')).upper())) &
            {'HIT','MISS','DYNAMIC','BYPASS','STALE','REVALIDATED','EXPIRED'}),
        cache_header_present=bool(headers.get('X-Cache') or headers.get('CF-Cache-Status')),
        etag_sha256=digest(headers.get('ETag')),
        server_sha256=digest(headers.get('Server')),
        node_sha256=digest(headers.get('X-Served-By')),
        cache_key_sha256=digest(headers.get('X-Cache-Key')),
        retry_after_present=bool(headers.get('Retry-After')))


class StudyClient(PolicyClient):
    def __init__(self, config):
        super().__init__(config.get('interval_seconds',2), config.get('timeout_seconds',8), 0)
        self.budget_seconds = min(config.get('max_seconds',180),180)
        self.deadline = time.monotonic()+self.budget_seconds
        self.limit = min(config.get('max_issues',20),20)
        self.wire_requests = 0
        self.starts = []
        self.revalidate = False
        self.stop_requested = False
        self.response_facts = None
        owner = self
        class Budget(BaseHandler):
            def http_request(self, request):
                remaining = owner.deadline-time.monotonic()
                if owner.stop_requested or owner.wire_requests >= owner.limit or remaining <= 0:
                    raise TimeoutError('Study request/time limit reached')
                owner.wire_requests += 1
                owner.starts.append(time.monotonic())
                request.timeout = min(request.timeout, remaining)
                return request
            https_request = http_request
        self.transport.__self__.add_handler(Budget())
        def bounded_sleep(seconds):
            if time.monotonic()+seconds >= self.deadline:
                raise TimeoutError('Study time limit reached')
            time.sleep(seconds)
        self.sleep = bounded_sleep

    def _open(self, req, timeout):
        self.response_facts = None
        if self.revalidate and not self.checking_policy:
            req.add_header('Cache-Control', 'no-cache')
        try:
            response = super()._open(req, timeout)
            self.response_facts = header_facts(response.headers)
            self.stop_requested |= self.response_facts['retry_after_present']
            return response
        except HTTPError as exc:
            self.response_facts = header_facts(exc.headers)
            self.stop_requested = True  # No retries or header changes after access/server errors.
            raise


def plan(nonce):
    known, operating = '마이홈차저', '중국산 승용차'
    new = 'CARMGZDIAG'+nonce
    result = []
    for gap, mode, pairs in [(2,'normal',[('known',known),('operating',operating),('new',new)]),
                              (6,'normal',[('known',known),('operating',operating)]),
                              (6,'revalidate',[('operating',operating),('new',new)])]:
        for group, query in pairs:
            for repeat in (1,2):
                result.append(dict(gap=gap,mode=mode,group=group,query=query,repeat=repeat))
    return result


def focused_plan(query):
    # Same URL across normal/revalidation/normal requests; do not rotate hosts or identity.
    cases = [('known','마이홈차저','normal'),('probe',query,'normal'),
             ('probe',query,'revalidate'),('probe',query,'normal'),('known','마이홈차저','normal')]
    return [dict(gap=6,mode=mode,group=group,query=q,repeat=n)
            for n,(group,q,mode) in enumerate(cases,1)]


def study(client, cases):
    rows = []
    consecutive_invalid = 0
    # At most one delayed retry for an invalid echo; it consumes the same hard budget.
    delayed_used = False
    previous_start = None
    queue = list(cases)
    stop = 'plan_completed'
    while queue:
        case = queue.pop(0)
        row = dict(case, sequence=len(rows)+1, at=datetime.now(timezone.utc).isoformat())
        client.interval = max(client.interval,case['gap'])
        client.revalidate = case['mode']=='revalidate'
        url = 'https://www.carmgz.kr/news/articleList.html?'+urlencode(dict(sc_area='A',view_type='sm',sc_word=case['query']))
        before = len(client.evidence)
        try:
            body = client.fetch(url)
            row.update(http_status=client.last_status,content_type=client.last_content_type,
                       headers=client.response_facts,diagnostics=search_diagnostics(body,case['query']),
                       response_url=safe_response_url(client.evidence[-1].get('final_url'),url),
                       redirects=sum(bool(e.get('location')) for e in client.evidence[before:]))
            row['actual_start_gap_seconds'] = round(client.starts[-1]-previous_start,3) if previous_start is not None else None
            previous_start = client.starts[-1]
            try:
                urls,total = parse_search(body,case['query'])
                row.update(valid=True,total=total,returned=len(urls),
                           known_article_found=any('idxno=22736' in u for u in urls) if case['group']=='known' else None)
                consecutive_invalid = 0
            except ValueError as exc:
                row.update(valid=False,error_code=getattr(exc,'code','invalid_response'))
                consecutive_invalid += 1
        except Exception as exc:
            row.update(valid=False,error_type=type(exc).__name__,http_status=client.last_status,
                       headers=client.response_facts)
            stop = 'transport_policy_or_budget_error'
            rows.append(row)
            break
        rows.append(row)
        if client.stop_requested:
            stop = 'server_requested_stop'
            break
        if consecutive_invalid >= 2:
            if delayed_used:
                stop = 'repeated_invalid_after_delayed_retry'
                break
            delayed_used = True
            # Repeat exactly the same GET with normal headers, never a cache variant.
            queue.insert(0,dict(case,gap=max(6,client.interval),mode='normal',delayed_retry=True))
        if case.get('delayed_retry') and not row['valid']:
            stop = 'delayed_retry_failed'
            break
    return dict(rows=rows, stop_reason=stop, wire_requests=client.wire_requests,
        request_cap=client.limit,time_cap_seconds=client.budget_seconds,
        elapsed_seconds=round(client.budget_seconds-(client.deadline-time.monotonic()),2),
        start_gaps_seconds=[round(b-a,3) for a,b in zip(client.starts,client.starts[1:])],
        outcomes=dict(Counter('valid' if r['valid'] else 'invalid' for r in rows)),
        proxy_configuration_present={k:bool(getproxies().get(k)) for k in ('http','https','all')})


def main():
    focus = os.environ.get('FOCUS_QUERY','').strip()
    if len(focus)>80 or any(ord(c)<32 for c in focus):
        raise ValueError('Focus must be a short public search phrase')
    result = study(StudyClient(load_config()),focused_plan(focus) if focus else plan(str(time.time_ns())))
    Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
    return 0 if result['stop_reason']=='plan_completed' else 1


if __name__=='__main__':
    sys.exit(main())
