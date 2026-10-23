"""Inspect only publisher landing/RSS help pages for advertised feed/contact links."""
import json
from html.parser import HTMLParser
from urllib.parse import urljoin
from pathlib import Path
from .multi import load_sources
from .policy_http import PolicyClient
from .storage import now

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        href=a.get('href','')
        if tag in ('a','link') and (any(w in href.lower() for w in ('rss','feed','partner','copyright','contact','company','customer'))
                                  or a.get('type','') in ('application/rss+xml','application/atom+xml')):
            self.links.append(dict(href=href,type=a.get('type'),rel=a.get('rel')))

def audit(sources=None, output="reports/discovery.json"):
    rows=[]
    for source in (sources if sources is not None else load_sources('publishers.json')):
        client=PolicyClient(2,10,0)
        row=dict(id=source['id'],publisher=source['publisher'],reference=source['official_reference'],checked_at=now(),links=[],error=None)
        try:
            body=client.fetch(row['reference'])
            parser=Links(); parser.feed(body.decode('utf-8',errors='replace'))
            row['links']=[dict(link,url=urljoin(row['reference'],link['href'])) for link in parser.links]
        except Exception as exc:
            row['error']=f'{type(exc).__name__}: {exc}'
        row['requests']=client.evidence
        rows.append(row)
        print(source['id'],len(row['links']),row['error'],flush=True)
    Path(output).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__': audit()
