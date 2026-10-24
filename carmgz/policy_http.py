"""Policy-aware HTTP client, including redirect destinations."""
from urllib.request import build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from .http import HttpClient, FetchError


class PolicyClient(HttpClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policies = {}
        self.evidence = []
        self.last_status = None
        self.last_content_type = None
        self.policy_result = 'not_checked'
        self.checking_policy = False
        owner = self
        class Redirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                owner.evidence.append({'url':req.full_url,'status':code,
                    'phase':'robots' if owner.checking_policy else 'feed','location':newurl})
                if owner.checking_policy:
                    if urlsplit(newurl).netloc != urlsplit(req.full_url).netloc:
                        raise FetchError('Cross-host robots redirect requires manual review')
                else:
                    owner.check_url(newurl)
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        self.transport = build_opener(Redirect()).open
        self.opener = self._open
    def _open(self, req, timeout):
        try:
            response = self.transport(req, timeout=timeout)
            self.last_status = response.status
            self.last_content_type = response.headers.get_content_type()
            self.evidence.append({'url':req.full_url,'status':response.status,'phase':'robots' if self.checking_policy else 'feed','final_url':response.geturl()})
            return response
        except HTTPError as exc:
            self.last_status = exc.code
            self.evidence.append({'url':req.full_url,'status':exc.code,'phase':'robots' if self.checking_policy else 'feed'})
            raise
    def check_url(self, url):
        self.policy_result = 'unavailable'
        u = urlsplit(url)
        if u.scheme not in ('http','https') or not u.netloc:
            raise FetchError('Invalid HTTP URL')
        origin = f'{u.scheme}://{u.netloc}'
        if origin not in self.policies:
            self.checking_policy = True
            try:
                try:
                    body = super().fetch(origin+'/robots.txt')
                except FetchError as exc:
                    if self.last_status not in (404,410):
                        raise FetchError(f'Policy unavailable: {exc}') from exc
                    body = b'User-agent: *\nAllow: /'
                policy = RobotFileParser()
                text = body.decode('utf-8-sig')
                if '<html' in text.lower() or not any('user-agent:' in line.lower() for line in text.splitlines()):
                    raise FetchError('Unrecognized robots response; manual review required')
                policy.parse(text.splitlines())
                self.policies[origin] = policy
            finally:
                self.checking_policy = False
        policy = self.policies[origin]
        if not policy.can_fetch(self.agent,url):
            self.policy_result = 'denied'
            raise FetchError('robots.txt disallows feed access')
        self.policy_result = 'allowed'
        rate = policy.request_rate(self.agent)
        self.interval = max(self.interval, policy.crawl_delay(self.agent) or 0,
                            rate.seconds/rate.requests if rate else 0)
    def fetch(self, url):
        self.last_status = None
        self.check_url(url)
        self.last_status = None
        return super().fetch(url)
