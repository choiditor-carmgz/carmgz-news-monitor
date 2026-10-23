import io
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from urllib.error import HTTPError
from carmgz.rss import PublisherRSS, canonical_url
from carmgz.providers import Article
from carmgz.multi_storage import MultiStorage
from carmgz.multi import collect_publishers, load_sources
from carmgz.policy_http import PolicyClient
from carmgz.http import FetchError

SOURCE=dict(id='paper',publisher='Paper',feed_url='https://example.org/rss',enabled=True,rss_status='candidate',permission='public_feed_policy_check')
A=Article('전기차 신차 출시','Paper','2026-10-23T01:00:00+00:00','https://example.org/a?id=1','a')

class MultiTests(unittest.TestCase):
    def test_atom_and_rss(self):
        body='''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>전기차</title><link href="https://example.org/a"/><published>2026-10-23T10:00:00+09:00</published></entry></feed>'''
        a=PublisherRSS(SOURCE).parse(body.encode())[0]
        self.assertEqual(a.publisher,'Paper')
        self.assertEqual(a.published_at,A.published_at)
        self.assertEqual(canonical_url('https://x/a?id=1&utm_source=r#f'),'https://x/a?id=1')
        self.assertNotEqual(canonical_url('https://x/a?id=1'),canonical_url('https://x/a?id=2'))
    def test_migration_retransmit_revision_and_cross_publisher(self):
        with tempfile.TemporaryDirectory() as d:
            from carmgz.storage import Storage
            path=Path(d)/'db'; old=Storage(path); old.close()
            s=MultiStorage(path); s.register([SOURCE]); r=s.start({})
            self.assertEqual(s.save_articles(r,SOURCE,[A],['전기차']),1)
            self.assertEqual(s.save_articles(r,SOURCE,[replace(A,source_id='retransmit',url='https://example.org/b')],['전기차']),0)
            updated=replace(A,title='전기차 신차 출시 수정')
            self.assertEqual(s.save_articles(r,SOURCE,[updated],['전기차']),0)
            other=dict(SOURCE,id='other',publisher='Other')
            self.assertEqual(s.save_articles(r,other,[replace(updated,publisher='Other')],['전기차']),1)
            self.assertEqual(s.db.execute('SELECT count(*) FROM article_relations').fetchone()[0],1)
            self.assertEqual(s.db.execute('SELECT count(*) FROM article_revisions').fetchone()[0],2)
            self.assertEqual(s.db.execute('SELECT count(*) FROM articles').fetchone()[0],2)
            self.assertEqual(s.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            s.close()
    def test_policy_failure_and_restricted_never_fetch(self):
        class Client:
            evidence=[]; policy_result='denied'
            def __init__(self,*args): pass
            def fetch(self,url): raise FetchError('denied')
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/'report.json'
            result=collect_publishers(dict(keywords=['전기차'],interval_seconds=2,timeout_seconds=1,retries=0),Path(d)/'db',
                [SOURCE,dict(SOURCE,id='held',enabled=False)],report,Client)
            data=json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(result['errors'],1)
            self.assertEqual([x['status'] for x in data['publishers']],['failed','held'])
            self.assertIsNone(data['publishers'][0]['http_status'])
    def test_policy_denial_and_missing_policy(self):
        c=PolicyClient(0,1,0,sleep=lambda _:None)
        c.opener=lambda req,timeout:io.BytesIO(b'User-agent: *\nDisallow: /rss')
        with self.assertRaises(FetchError): c.fetch(SOURCE['feed_url'])
        self.assertEqual(c.policy_result,'denied')
        c=PolicyClient(0,1,0,sleep=lambda _:None)
        c.opener=lambda req,timeout:io.BytesIO(b'<html>challenge</html>')
        with self.assertRaises(FetchError): c.fetch(SOURCE['feed_url'])
    def test_registry(self):
        sources=load_sources('publishers.json')
        self.assertGreaterEqual(len(sources),30)
        self.assertLessEqual(len(sources),50)

class AdditionalTests(unittest.TestCase):
    def test_two_publishers_failure_isolation_and_repeated_collection(self):
        class Client:
            def __init__(self,*args): self.evidence=[]; self.policy_result='allowed'
            def fetch(self,url):
                if 'bad' in url: raise FetchError('HTTP 403')
                self.evidence=[dict(url=url,status=200,phase='feed')]
                return '<rss><channel><item><title>전기차 출시</title><link>https://example.org/1</link></item></channel></rss>'.encode()
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(keywords=['전기차'],interval_seconds=2,timeout_seconds=1,retries=0)
            sources=[dict(SOURCE,id='bad',feed_url='https://bad.test/rss'),SOURCE]
            first=collect_publishers(cfg,Path(d)/'db',sources,client_factory=Client)
            second=collect_publishers(cfg,Path(d)/'db',sources,client_factory=Client)
            self.assertEqual(first,dict(fetched=1,inserted=1,duplicates=0,errors=1))
            self.assertEqual(second,dict(fetched=1,inserted=0,duplicates=1,errors=1))
    def test_old_feed_is_not_current_success(self):
        class Client:
            evidence=[]; policy_result='allowed'
            def __init__(self,*args): pass
            def fetch(self,url):
                return b'<rss><channel><item><title>EV</title><link>https://example.org/1</link><pubDate>2024.10.29</pubDate></item></channel></rss>'
        with tempfile.TemporaryDirectory() as d:
            report=Path(d)/'report.json'
            result=collect_publishers(dict(keywords=['EV'],interval_seconds=2,timeout_seconds=1,retries=0),Path(d)/'db',[SOURCE],report,Client)
            self.assertEqual(result['inserted'],0)
            data=json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(data['publishers'][0]['status'],'stale_feed')
    def test_same_title_outside_retransmit_window_stays_separate(self):
        with tempfile.TemporaryDirectory() as d:
            s=MultiStorage(Path(d)/'db'); s.register([SOURCE]); run=s.start({})
            s.save_articles(run,SOURCE,[A],['전기차'])
            self.assertEqual(s.save_articles(run,SOURCE,[replace(A,source_id='later',url='https://example.org/later',published_at='2026-11-23T01:00:00+00:00')],['전기차']),1)
            s.close()
    def test_redirect_destination_policy_is_checked(self):
        from urllib.request import Request
        c=PolicyClient(0,1,0,sleep=lambda _:None)
        c.opener=lambda req,timeout:io.BytesIO(b'User-agent: *\nDisallow: /')
        redirect=next(h for h in c.transport.__self__.handlers if type(h).__name__=='Redirect')
        with self.assertRaises(FetchError):
            redirect.redirect_request(Request('https://a.test/rss'),None,302,'found',{},'https://b.test/rss')
    def test_atomic_storage_failure(self):
        with tempfile.TemporaryDirectory() as d:
            s=MultiStorage(Path(d)/'db'); s.register([SOURCE]); r=s.start({})
            with self.assertRaises(AttributeError): s.save_articles(r,SOURCE,[A,None],['전기차'])
            self.assertEqual(s.db.execute('SELECT count(*) FROM articles').fetchone()[0],0)
            s.close()

if __name__=='__main__': unittest.main()
