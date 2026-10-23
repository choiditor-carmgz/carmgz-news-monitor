"""Publisher-owned RSS adapter; no article-body requests."""
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import re
import unicodedata
import xml.etree.ElementTree as ET
from .providers import Article


def canonical_url(url):
    u = urlsplit(url)
    query = [(k,v) for k,v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path,urlencode(query),''))


def normalized_title(title):
    text = unicodedata.normalize('NFKC', title).lower()
    text = re.sub(r'\[(?:종합\d*보?|속보|재송|수정|업데이트)[^\]]*\]', '', text)
    return re.sub(r'[^\w가-힣]', '', text)


class PublisherRSS:
    def __init__(self, source):
        self.source = source
        self.name = source['id']
    def url(self, keyword=''):
        return self.source['feed_url']
    def parse(self, body):
        if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
            raise ValueError('DTD/entities forbidden')
        root = ET.fromstring(body)
        atom = '{http://www.w3.org/2005/Atom}'
        if root.tag == 'rss' and root.find('channel') is not None:
            items = root.findall('./channel/item')
        elif root.tag == atom+'feed':
            items = root.findall(atom+'entry')
        else:
            raise ValueError('Expected RSS or Atom feed')
        result = []
        for item in items:
            title = (item.findtext('title') or item.findtext(atom+'title') or '').strip()
            url = (item.findtext('link') or '').strip()
            if not url:
                links = item.findall(atom+'link')
                url = next((x.get('href','') for x in links if x.get('rel','alternate') == 'alternate'), '')
            if not title or urlsplit(url).scheme not in ('https','http'):
                raise ValueError('Item missing title or valid link')
            raw = (item.findtext('pubDate') or item.findtext('{http://purl.org/dc/elements/1.1/}date')
                   or item.findtext(atom+'published') or item.findtext(atom+'updated'))
            published = None
            if raw:
                try:
                    dt = parsedate_to_datetime(raw)
                except (ValueError, TypeError):
                    try:
                        dt = datetime.fromisoformat(raw.replace('Z','+00:00'))
                    except ValueError:
                        dt = datetime.strptime(raw.strip(), '%Y.%m.%d')
                published = dt.replace(tzinfo=dt.tzinfo or timezone(timedelta(hours=9))).astimezone(timezone.utc).isoformat()
            result.append(Article(title,self.source['publisher'],published,canonical_url(url),
                                  item.findtext('guid') or item.findtext(atom+'id') or canonical_url(url)))
        return result


def matching_keywords(article, keywords):
    from .relevance import HUNGER, automotive_terms
    title = unicodedata.normalize('NFKC',article.title).casefold()
    if HUNGER.search(article.title):
        return []
    return list(dict.fromkeys([w for w in keywords if unicodedata.normalize('NFKC',w).casefold() in title]
                              + automotive_terms(article.title)))
