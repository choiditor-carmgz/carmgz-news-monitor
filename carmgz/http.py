import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

class FetchError(Exception):
    pass

class HttpClient:
    agent = 'CARMGZNewsMonitor/0.1'
    def __init__(self, interval=5, timeout=25, retries=2, opener=urlopen, sleep=time.sleep, clock=time.monotonic):
        self.interval, self.timeout, self.retries = interval, timeout, retries
        self.opener, self.sleep, self.clock = opener, sleep, clock
        self.last = None
        self.policy = None
    def _wait(self, extra=0):
        remaining = 0 if self.last is None else self.interval - (self.clock()-self.last)
        self.sleep(max(0, remaining, extra))
        self.last = self.clock()
    def fetch(self, url):
        if self.policy is not None and not self.policy.can_fetch(self.agent, url):
            raise FetchError('robots.txt disallows feed access')
        extra = 0
        for attempt in range(self.retries+1):
            self._wait(extra)
            try:
                with self.opener(Request(url, headers={'User-Agent':self.agent,
                         'Accept':'application/rss+xml, application/xml, text/plain'}), timeout=self.timeout) as r:
                    body = r.read(5_000_001)
                    if len(body) > 5_000_000:
                        raise FetchError('Response exceeds 5 MB')
                    return body
            except HTTPError as exc:
                if exc.code not in (429,500,502,503,504) or attempt == self.retries:
                    raise FetchError(f'HTTP {exc.code}: {url}') from exc
                value = exc.headers.get('Retry-After', '')
                try:
                    extra = float(value)
                except ValueError:
                    try:
                        extra = (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        extra = 0
                if extra > 300:
                    raise FetchError('Retry-After exceeds 300s; defer to later run') from exc
                extra = max(extra, self.interval * 2**attempt)
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == self.retries:
                    raise FetchError(f'Network failure: {exc}') from exc
                extra = self.interval * 2**attempt
        raise FetchError('Retries exhausted')
    def check_robots(self):
        body = self.fetch('https://news.google.com/robots.txt')
        policy = RobotFileParser()
        policy.parse(body.decode('utf-8').splitlines())
        self.policy = policy
        delay = policy.crawl_delay(self.agent)
        rate = policy.request_rate(self.agent)
        self.interval = max(self.interval, delay or 0, rate.seconds/rate.requests if rate else 0)
