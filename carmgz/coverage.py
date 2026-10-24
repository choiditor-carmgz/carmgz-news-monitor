"""On-demand CARMGZ evidence checks; no full-text archive or ranking changes."""
from datetime import datetime, timedelta, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urljoin, urlsplit

from .analysis import EVENTS, timestamp
from .policy_http import PolicyClient
from .rss import normalized_title

STATUSES = ('보도 완료', '미보도', '후속 보도 검토', '확인 필요', '확인 불가')
RULE_VERSION = 'v2-query-validated'
HOSTS = {'carmgz.kr', 'www.carmgz.kr'}


class SearchResponseError(ValueError):
    def __init__(self, message, code, echoed_query=None):
        super().__init__(message)
        self.code, self.echoed_query = code, echoed_query


def own_url(url):
    """Apex and www are one publisher; reject lookalikes and non-HTTP links."""
    u = urlsplit(url)
    if u.scheme not in ('https', 'http') or u.hostname not in HOSTS or u.port:
        raise ValueError('Not a CARMGZ article URL')
    return 'https://www.carmgz.kr'+u.path+('?' + u.query if u.query else '')


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(); self.values = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            self.values[a.get('property') or a.get('name')] = a.get('content', '')


def parse_article(body, url):
    text = body.decode('utf-8-sig'); parser = Metadata(); parser.feed(text)
    title = parser.values.get('og:title', '').split(' - 카매거진')[0].strip()
    published = parser.values.get('article:published_time')
    if not title or not timestamp(published):
        raise ValueError('Article metadata missing; no coverage assertion')
    # Body is transient comparison evidence only. Never put full text in SQLite/JSON.
    section = re.search(r'<div[^>]*id=["\']article-view-content-div["\'][^>]*>(.*?)<!--', text, re.S)
    content = unescape(re.sub('<[^>]+>', ' ', section.group(1))) if section else ''
    return dict(title=unescape(title), published_at=published, url=own_url(url), _content=content[:30000])


def parse_search(body, query=None):
    text = body.decode('utf-8-sig')
    if query is not None:
        echo = re.search(r'''params\[['"]sc_word['"]\]\s*=\s*(['"])(.*?)\1''',text,re.S)
        actual = unescape(echo.group(2)) if echo else None
        if echo and echo.group(1)=='"':
            try: actual=json.loads('"'+echo.group(2)+'"')
            except ValueError: actual=None
        if actual is None or ' '.join(actual.split()) != ' '.join(query.split()):
            code = 'query_echo_missing' if not echo else 'query_echo_invalid' if actual is None else 'query_not_applied'
            raise SearchResponseError('Search query was not applied/echoed; unfiltered archive is not a valid search result', code, actual)
    main = re.search(r'<article\b[^>]*id=["\']section-list["\'][^>]*>(.*?)</article>', text, re.S|re.I)
    total = re.search(r"params\[['\"]total['\"]\]\s*=\s*['\"]?(\d+)", text)
    if not main or not total:
        raise SearchResponseError('Unrecognized search layout/total; cannot infer no coverage', 'search_layout_changed')
    urls = []
    for href in re.findall(r'href=["\']([^"\']*articleView\.html\?[^"\']+)["\']', main.group(1), re.I):
        try:
            url = own_url(urljoin('https://www.carmgz.kr', unescape(href)))
            if url not in urls:
                urls.append(url)
        except ValueError:
            continue
    if int(total.group(1)) and not urls:
        raise SearchResponseError('Positive search total without parseable main results', 'search_results_unparseable')
    if not int(total.group(1)) and urls:
        raise SearchResponseError('Zero search total with article results; inconsistent response', 'search_total_inconsistent')
    return urls, int(total.group(1))


def tokens(text):
    return set(re.findall(r'[A-Za-z][A-Za-z0-9]+|[가-힣]{2,}|\d+(?:\.\d+)?', text.casefold()))


def queries(issue):
    title = issue['articles'][0]['title']
    for _, _, anchors in EVENTS:
        matches = [re.search(p, title, re.I) for p in anchors]
        if all(matches):
            # The search uses literal phrases: rare anchor fallback avoids zero-result trap.
            words = [m.group(0) for m in matches]
            return [' '.join(words[:2]), words[0]]
    words = re.findall(r'[A-Za-z][A-Za-z0-9]+|[가-힣]{2,}', title)
    stop = {'사진','포토','종합','속보','출시','공개','발표','자동차','현대차','기아'}
    specific = [w for w in words if w not in stop]
    quoted = re.search(r'''[‘“'"]([^’”'"]{2,40})[’”'"]''', title)
    if quoted:
        anchor = quoted.group(1)
        return list(dict.fromkeys([specific[0]+' '+anchor if specific else anchor, anchor]))
    # Company-only fallbacks drown old events in recent results. Prefer model/event phrase.
    anchor = ' '.join(specific[1:4]) if len(specific)>1 else (specific[0] if specific else title)
    return list(dict.fromkeys([' '.join(specific[:2]), anchor]))


def compare(issue, article):
    """Multiple event anchors + compatible time/facts, never company alone."""
    titles = [a['title'] for a in issue['articles']]
    old = article['title']; content = old+' '+article.get('_content', '')
    common = set().union(*(tokens(t) & tokens(old) for t in titles))
    newest = max((timestamp(a['published_at']) for a in issue['articles'] if timestamp(a['published_at'])), default=None)
    prior = timestamp(article['published_at'])
    for title in titles:
        conflict = any(set(re.findall(p, title)) and set(re.findall(p, old)) and
                       set(re.findall(p, title)) != set(re.findall(p, old))
                       for p in (r'20\d{2}년', r'\d+\s*대', r'\d+\s*억',
                                 r'발리|수라바야|서울|부산|대구|인천|광주|대전|울산|제주'))
        conflict = conflict or any(bool(re.search(p,title)) != bool(re.search(p,old))
                                   for p in (r'리콜|결함',r'사망|사고',r'생산\s*중단',r'화재'))
        # Where the source title omits a quantity, consult transient body evidence.
        for pattern in (r'\d+\s*대', r'\d+\s*억'):
            claimed=set(re.findall(pattern,title)); stated=set(re.findall(pattern,old))
            body_facts=set(re.findall(pattern,article.get('_content','')))
            if claimed and not stated and body_facts and claimed.isdisjoint(body_facts):
                conflict=True
        anchors = next((a for _,_,a in EVENTS if all(re.search(p,title,re.I) and re.search(p,old,re.I) for p in a)), None)
        exact = normalized_title(title) == normalized_title(old)
        action = re.search(r'공급|출시|공개|계약|리콜|제휴|발표|평가|초청|개최', title)
        # Sufficient title facts; body confirms event terms when available.
        # A shared company/action is insufficient: generic matches stay uncertain.
        # Additional event rules can be reviewed and added without changing rank scores.
        strong = bool(anchors or exact)
        near = prior and newest and abs((newest-prior).total_seconds()) <= 72*3600
        # Only an explicit change of an already identified event may be a follow-up.
        change = re.search(r'리콜\s*대상\s*확대|(?:투자|계획|출시\s*일정|정책|규제).*(?:변경|철회)|생산\s*재개', title)
        if strong and change and prior and newest and newest > prior and not re.search(change.group(0), content):
            return '후속 보도 검토', '동일 사건 단서와 기존 보도 이후의 명시적 변경 표현 확인: '+change.group(0)
        if strong and near and not conflict:
            return '보도 완료', '복수 핵심 사건 단서·행동·발행 시점 일치 (규칙 기반, 편집 확인 권장)'
    if len(common) >= 2:
        return '확인 필요', '관련 단어는 일치하지만 핵심 사건·시점·수치의 동일성 미확정'
    return None, None


class Checker:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or PolicyClient(config.get('interval_seconds',2),config.get('timeout_seconds',8),0)
        self.deadline = time.monotonic()+min(config.get('max_seconds',180),180)
        if hasattr(self.client,'sleep'):
            original_sleep = self.client.sleep
            def bounded_sleep(seconds):
                if time.monotonic()+seconds >= self.deadline:
                    raise TimeoutError('CARMGZ request budget: defer, never bypass crawl delay')
                original_sleep(seconds)
            self.client.sleep = bounded_sleep
        self.article_cache = {}
        self.search_cache = {}
        self.search_metadata = {}
        self.circuit_open = False
        self.last_search_failure = None
        self.same_search_failures = 0

    def search_failure(self, exc):
        if isinstance(exc, SearchResponseError):
            code = exc.code
        else:
            http = re.search(r'HTTP\s+(\d{3})', str(exc))
            code = 'http_'+http.group(1) if http else ('budget_exhausted' if time.monotonic() >= self.deadline else 'network_error')
        if code != 'budget_exhausted':
            self.same_search_failures = self.same_search_failures+1 if code == self.last_search_failure else 1
            self.last_search_failure = code
            self.circuit_open = self.same_search_failures >= 2
        return code

    def fetch(self, url):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('CARMGZ execution budget exhausted')
        return self.client.fetch(own_url(url))

    def check(self, issue, at):
        result = dict(status='확인 불가', rule_version=RULE_VERSION, checked_at=datetime.now(timezone.utc).isoformat(), search_success=False,
                      queries=[], searches=[], matches=[], scope=self.config.get('scope_note',''),
                      date_limit=None, complete=False, reason='검색 범위 불완전', errors=[], search_outcome='error')
        related = []; all_totals = []
        for query in queries(issue)[:self.config.get('max_queries',2)]:
            if self.circuit_open:
                break
            result['queries'].append(query)
            search = dict(query=query,at=datetime.now(timezone.utc).isoformat(),success=False)
            result['searches'].append(search)
            try:
                url = 'https://www.carmgz.kr/news/articleList.html?'+urlencode(dict(sc_area='A',view_type='sm',sc_word=query))
                search['cached_in_run'] = query in self.search_cache
                if query not in self.search_cache:
                    self.search_cache[query] = parse_search(self.fetch(url), query=query)
                    evidence = getattr(self.client,'evidence',[])
                    self.search_metadata[query] = dict(http_status=getattr(self.client,'last_status',None),
                        response_url=evidence[-1].get('final_url') if evidence else None)
                urls, total = self.search_cache[query]; all_totals.append(total)
                search.update(success=True,total=total,returned=len(urls),url=url,outcome='results' if total else 'empty',
                              **self.search_metadata[query])
                result['search_success'] = True
                self.same_search_failures = 0
                self.last_search_failure = None
            except Exception as exc:
                search.update(outcome='error',error=type(exc).__name__+': '+str(exc),error_code=self.search_failure(exc),
                              http_status=getattr(self.client,'last_status',None))
                if isinstance(exc, SearchResponseError):
                    search['echoed_query'] = exc.echoed_query
                evidence = getattr(self.client,'evidence',[])
                if evidence:
                    search['response_url'] = evidence[-1].get('final_url') or evidence[-1].get('url')
                result['errors'].append(search['error'])
                continue
            for url in urls[:self.config.get('max_articles_per_issue',2)]:
                try:
                    if url not in self.article_cache:
                        self.article_cache[url] = parse_article(self.fetch(url),url)
                    article = self.article_cache[url]
                    status, reason = compare(issue, article)
                    if status:
                        public = {k:v for k,v in article.items() if not k.startswith('_')}
                        evidence = dict(public, reason=reason, assessment=status)
                        if not any(m['url']==url for m in result['matches']):
                            result['matches'].append(evidence)
                        related.append((status,reason))
                except Exception as exc:
                    error = type(exc).__name__+': '+str(exc)
                    search.setdefault('article_errors',[]).append(dict(url=url,error=error))
                    result['errors'].append(error)
        result['result_totals'] = all_totals
        result['circuit_open'] = self.circuit_open
        if result['search_success']:
            result['search_outcome'] = ('partial_error' if any(s.get('outcome')=='error' for s in result['searches'])
                                        else 'results' if any(all_totals) else 'empty')
        if related:
            status, reason = min(related, key=lambda r: ['후속 보도 검토','보도 완료','확인 필요'].index(r[0]))
            result.update(status=status, reason=reason)
        elif not result['search_success']:
            result['reason']='검색 응답 검증 실패 또는 접근 불가: 미보도로 판정하지 않음'
        elif result['search_outcome'] == 'empty':
            result['reason']='공식 검색 결과 0건: 검색 범위 내 미발견이며 미보도 확정 아님'
        elif result['search_outcome'] == 'results':
            result['reason']='검색 결과는 있으나 동일 사건 보도 근거 미확정'
        elif result['search_outcome'] == 'partial_error':
            result['reason']='일부 검색 요청 실패: 성공 응답 범위만 확인, 미보도 확정 아님'
        # No finite first-page keyword search proves absence from the whole archive.
        # The '미보도' state is reserved for a future verified exhaustive adapter.
        return result


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS carmgz_checks(
        issue_id TEXT PRIMARY KEY REFERENCES issues(id), checked_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL, payload TEXT NOT NULL)''')


def display_status(result):
    if result.get('status') in ('보도 완료','후속 보도 검토','확인 필요'):
        return result['status']
    if not result.get('checked_at'):
        return '검색 대기'
    if not result.get('search_success') or result.get('errors'):
        return '검색 실패'
    return '검색 범위 내 미발견'


def public_result(result):
    # Search requests/errors stay in private SQLite, not in the dashboard payload.
    public = {k:result[k] for k in ('status','checked_at','search_success','search_outcome',
        'reason','scope','date_limit','matches','cached','display_status') if k in result}
    public['display_status'] = result.get('display_status') or display_status(result)
    return public


def verify_issues(db, report, at, config, force=False, checker=None):
    started = time.monotonic()
    attempted = query_attempts = 0
    migrate(db)
    from .editorial import rank, material_signature
    top = report.get('rankings',{}).get('industry')
    if top is None:
        top = rank(report['issues'])
    targets = {i['id'] for i in top[:max(0,min(10,config.get('max_issues',20),20))]}
    pending = []
    for issue in report['issues']:
        signature = material_signature(issue)
        row = db.execute('SELECT checked_at,fingerprint,payload FROM carmgz_checks WHERE issue_id=?',(issue['id'],)).fetchone()
        cached = json.loads(row[2]) if row else None
        if row and row[1]!=signature and cached.get('rule_version')==RULE_VERSION:
            # Upgrade an unchanged legacy article fingerprint without another HTTP search.
            legacy=hashlib.sha256(json.dumps(sorted((a['title'],a['published_at']) for a in issue['articles']),ensure_ascii=False).encode()).hexdigest()
            if row[1]==legacy:
                db.execute('UPDATE carmgz_checks SET fingerprint=? WHERE issue_id=?',(signature,issue['id']))
                row=(row[0],signature,row[2])
        fresh = row and timestamp(row[0]) and at-timestamp(row[0]) < timedelta(hours=config.get('cache_hours',6))
        # Briefings and elapsed TTL alone do not force a repeat of successful unchanged searches.
        completed = cached and (cached.get('status') in ('보도 완료','후속 보도 검토') or
                                (cached.get('search_success') and not cached.get('errors')))
        reusable = row and row[1]==signature and cached.get('rule_version','v1')==RULE_VERSION and (completed or fresh)
        if reusable:
            issue['carmgz'] = dict(cached, cached=True)
        else:
            issue['carmgz'] = dict(status='확인 불가',checked_at=None,search_success=False,matches=[],queries=[],
                                   reason='이번 실행 검색 대기·시간 예산 제한',scope=config.get('scope_note',''),date_limit=None,search_outcome='pending')
            if cached:
                issue['carmgz']['previous_check'] = {k:cached.get(k) for k in ('status','checked_at')}
            if issue['id'] in targets:
                pending.append((issue,signature))
            else:
                issue['carmgz']['reason']='TOP 10 보조 검색 대상 외: 편집자 확인 가능'
    order={i['id']:n for n,i in enumerate(top)}
    pending.sort(key=lambda x:order[x[0]['id']])
    # No HTTP client, robots lookup or timer is needed when every target is cached.
    checker = checker or (Checker(config) if pending else None)
    for issue, signature in pending:
        if time.monotonic() >= checker.deadline or getattr(checker,'circuit_open',False):
            break
        try:
            attempted += 1
            result = checker.check(issue, at)
        except Exception as exc:
            checker.circuit_open = True
            result = dict(status='확인 불가',rule_version=RULE_VERSION,checked_at=datetime.now(timezone.utc).isoformat(),
                search_success=False,search_outcome='error',matches=[],errors=[type(exc).__name__],
                reason='선택적 보도 검색 오류: 뉴스 순위에는 영향 없음')
        issue['carmgz'] = result
        query_attempts += sum(not s.get('cached_in_run',False) for s in result.get('searches',[]))
        db.execute('INSERT OR REPLACE INTO carmgz_checks VALUES(?,?,?,?)',
                   (issue['id'],result['checked_at'],signature,json.dumps(result,ensure_ascii=False)))
    if getattr(checker,'circuit_open',False):
        for issue, _ in pending:
            if issue['carmgz'].get('search_outcome') == 'pending':
                issue['carmgz'].update(search_outcome='deferred',reason='동일 검색 응답 오류 반복으로 이번 실행 검색 중단')
    for issue in report['issues']:
        issue['carmgz']['display_status'] = display_status(issue['carmgz'])
    report['coverage_summary'] = dict(target_issues=len(targets),attempted_issues=attempted,
        search_query_attempts=query_attempts,cached_issues=sum(bool(i['carmgz'].get('cached')) for i in report['issues']),
        elapsed_seconds=round(time.monotonic()-started,3),max_issues=min(config.get('max_issues',20),20),
        max_seconds=min(config.get('max_seconds',180),180))
    return report


def load_config(path='coverage.json'):
    return json.loads(Path(path).read_text(encoding='utf-8'))
