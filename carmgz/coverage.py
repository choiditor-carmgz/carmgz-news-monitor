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
HOSTS = {'carmgz.kr', 'www.carmgz.kr'}


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


def parse_search(body):
    text = body.decode('utf-8-sig')
    main = re.search(r'<article\b[^>]*id=["\']section-list["\'][^>]*>(.*?)</article>', text, re.S|re.I)
    total = re.search(r"params\[['\"]total['\"]\]\s*=\s*['\"]?(\d+)", text)
    if not main or not total:
        raise ValueError('Unrecognized search layout/total; cannot infer no coverage')
    urls = []
    for href in re.findall(r'href=["\']([^"\']*articleView\.html\?[^"\']+)["\']', main.group(1), re.I):
        try:
            url = own_url(urljoin('https://www.carmgz.kr', unescape(href)))
            if url not in urls:
                urls.append(url)
        except ValueError:
            continue
    if int(total.group(1)) and not urls:
        raise ValueError('Positive search total without parseable main results')
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
        self.deadline = time.monotonic()+config.get('max_seconds',180)
        self.article_cache = {}
        self.search_cache = {}

    def fetch(self, url):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('CARMGZ execution budget exhausted')
        return self.client.fetch(own_url(url))

    def check(self, issue, at):
        result = dict(status='확인 불가', checked_at=datetime.now(timezone.utc).isoformat(), search_success=False,
                      queries=[], searches=[], matches=[], scope=self.config.get('scope_note',''),
                      date_limit=None, complete=False, reason='검색 범위 불완전', errors=[])
        related = []; all_totals = []
        for query in queries(issue)[:self.config.get('max_queries',2)]:
            result['queries'].append(query)
            search = dict(query=query,at=datetime.now(timezone.utc).isoformat(),success=False)
            result['searches'].append(search)
            try:
                url = 'https://www.carmgz.kr/news/articleList.html?'+urlencode(dict(sc_area='A',view_type='sm',sc_word=query))
                if query not in self.search_cache:
                    self.search_cache[query] = parse_search(self.fetch(url))
                urls, total = self.search_cache[query]; all_totals.append(total)
                search.update(success=True,total=total,returned=len(urls),url=url,
                              http_status=getattr(self.client,'last_status',None))
                result['search_success'] = True
                for url in urls[:self.config.get('max_articles_per_issue',2)]:
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
                search['error'] = type(exc).__name__+': '+str(exc)
                result['errors'].append(type(exc).__name__+': '+str(exc))
        result['result_totals'] = all_totals
        if related:
            status, reason = min(related, key=lambda r: ['후속 보도 검토','보도 완료','확인 필요'].index(r[0]))
            result.update(status=status, reason=reason)
        # No finite first-page keyword search proves absence from the whole archive.
        # The '미보도' state is reserved for a future verified exhaustive adapter.
        return result


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS carmgz_checks(
        issue_id TEXT PRIMARY KEY REFERENCES issues(id), checked_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL, payload TEXT NOT NULL)''')


def verify_issues(db, report, at, config, force=False, checker=None):
    migrate(db)
    checker = checker or Checker(config)
    pending = []
    for issue in report['issues']:
        signature = hashlib.sha256(json.dumps(sorted((a['title'],a['published_at']) for a in issue['articles']),ensure_ascii=False).encode()).hexdigest()
        row = db.execute('SELECT checked_at,fingerprint,payload FROM carmgz_checks WHERE issue_id=?',(issue['id'],)).fetchone()
        cached = json.loads(row[2]) if row else None
        fresh = row and timestamp(row[0]) and at-timestamp(row[0]) < timedelta(hours=config.get('cache_hours',6))
        if fresh and row[1]==signature and not force:
            issue['carmgz'] = dict(cached, cached=True)
        else:
            issue['carmgz'] = dict(status='확인 불가',checked_at=None,search_success=False,matches=[],queries=[],
                                   reason='이번 실행 검색 대기·시간 예산 제한',scope=config.get('scope_note',''),date_limit=None)
            if cached:
                issue['carmgz']['previous_check'] = {k:cached.get(k) for k in ('status','checked_at')}
            pending.append((row is not None, issue, signature))
    # New issues first, then oldest checked. Do not starve the remaining backlog.
    pending.sort(key=lambda x:(x[0], db.execute('SELECT checked_at FROM carmgz_checks WHERE issue_id=?',(x[1]['id'],)).fetchone()[0] if x[0] else '', -x[1]['importance_score']))
    for _, issue, signature in pending[:config.get('max_issues',20)]:
        if time.monotonic() >= checker.deadline:
            break
        result = checker.check(issue, at)
        issue['carmgz'] = result
        db.execute('INSERT OR REPLACE INTO carmgz_checks VALUES(?,?,?,?)',
                   (issue['id'],result['checked_at'],signature,json.dumps(result,ensure_ascii=False)))
    return report


def load_config(path='coverage.json'):
    return json.loads(Path(path).read_text(encoding='utf-8'))
