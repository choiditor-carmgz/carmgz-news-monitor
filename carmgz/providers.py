"""Provider contract and Google News adapter."""
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit
import hashlib
import unicodedata
import xml.etree.ElementTree as ET

@dataclass(frozen=True)
class Article:
    title: str
    publisher: str
    published_at: str | None
    url: str
    source_id: str

class Provider(Protocol):
    name: str
    def url(self, keyword: str) -> str: ...
    def parse(self, body: bytes) -> list[Article]: ...

def identity(a):
    if a.published_at and a.publisher:
        fields = [a.publisher, a.title, a.published_at]
    else:
        u = urlsplit(a.url)
        fields = [urlunsplit((u.scheme, u.netloc.lower(), u.path, '', ''))]
    value = '\x1f'.join(' '.join(unicodedata.normalize('NFKC', f).split()) for f in fields)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

class GoogleNews:
    name = 'google_news'
    def __init__(self, days=7):
        self.days = days
    def url(self, keyword):
        return 'https://news.google.com/rss/search?' + urlencode({
            'q': f'{keyword} when:{self.days}d', 'hl':'ko', 'gl':'KR', 'ceid':'KR:ko'})
    def parse(self, body):
        if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
            raise ValueError('DTD/entities forbidden')
        root = ET.fromstring(body)
        if root.tag != 'rss' or root.find('channel') is None:
            raise ValueError('Expected RSS channel')
        result = []
        for item in root.findall('./channel/item'):
            title = (item.findtext('title') or '').strip()
            url = (item.findtext('link') or '').strip()
            publisher = (item.findtext('source') or '').strip()
            if not title or urlsplit(url).scheme not in ('https','http'):
                raise ValueError('Item missing title or valid link')
            if publisher and title.endswith(' - ' + publisher):
                title = title[:-len(publisher)-3].rstrip()
            published = None
            if item.findtext('pubDate'):
                dt = parsedate_to_datetime(item.findtext('pubDate'))
                published = dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
            result.append(Article(title, publisher, published, url, item.findtext('guid') or url))
        return result
