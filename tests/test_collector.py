import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch
from carmgz.providers import Article, GoogleNews, identity
from carmgz.storage import Storage
from carmgz.http import HttpClient, FetchError
from carmgz.__main__ import collect, load_config

RSS = b"""<rss><channel><item><title>EV launch - Paper</title><source>Paper</source>
<link>https://news.google.com/rss/articles/a?oc=5</link><guid>a</guid>
<pubDate>Fri, 23 Oct 2026 01:00:00 GMT</pubDate></item></channel></rss>"""

class ProviderTests(unittest.TestCase):
    def test_parse(self):
        a = GoogleNews().parse(RSS)[0]
        self.assertEqual(a.title, 'EV launch')
        self.assertEqual(a.publisher, 'Paper')
        self.assertEqual(a.published_at, '2026-10-23T01:00:00+00:00')
        self.assertEqual(a.source_id, 'a')
    def test_bad_xml_and_html(self):
        for body in (b'<html/>', b'<rss>', b'<!DOCTYPE rss><rss><channel/></rss>'):
            with self.assertRaises(Exception):
                GoogleNews().parse(body)
    def test_url(self):
        self.assertIn('ceid=KR%3Ako', GoogleNews().url('EV'))
        self.assertIn('when%3A7d', GoogleNews().url('EV'))
    def test_identity(self):
        a = GoogleNews().parse(RSS)[0]
        self.assertEqual(identity(a), identity(replace(a,url='https://example.com/other',source_id='b')))
        self.assertNotEqual(identity(a),identity(replace(a,publisher='Other')))

class StorageTests(unittest.TestCase):
    def test_dedup_keywords_restart_timestamps(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'news.db'
            a = GoogleNews().parse(RSS)[0]
            s = Storage(path)
            run = s.start({})
            with patch('carmgz.storage.now',return_value='2026-10-23T01:00:00+00:00'):
                s.record(run,'EV','google', [a])
            with patch('carmgz.storage.now',return_value='2026-10-23T02:00:00+00:00'):
                s.record(run,'car','google',[replace(a,source_id='b',url='https://example.com/b')])
            self.assertEqual(s.finish(run),dict(fetched=2,inserted=1,duplicates=1,errors=0))
            s.close()
            s = Storage(path)
            run = s.start({})
            s.record(run,'EV','google',[a])
            self.assertEqual(s.finish(run)['inserted'],0)
            self.assertEqual(s.db.execute('SELECT count(*) FROM articles').fetchone()[0],1)
            self.assertEqual(s.db.execute('SELECT count(*) FROM article_keywords').fetchone()[0],2)
            self.assertEqual(s.db.execute('SELECT count(*) FROM article_sources').fetchone()[0],2)
            first,last = s.db.execute('SELECT first_collected_at,last_seen_at FROM articles').fetchone()
            self.assertEqual(first,'2026-10-23T01:00:00+00:00')
            self.assertNotEqual(first,last)
            self.assertEqual(s.db.execute('SELECT count(*) FROM article_metrics').fetchone()[0],0)
            self.assertEqual(s.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            s.close()
    def test_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            s = Storage(Path(d)/'db')
            r = s.start({})
            a = GoogleNews().parse(RSS)[0]
            with self.assertRaises(AttributeError):
                s.record(r,'EV','google',[a,None])
            self.assertEqual(s.db.execute('SELECT count(*) FROM articles').fetchone()[0],0)
            s.close()
    def test_error_and_interrupted_run(self):
        with tempfile.TemporaryDirectory() as d:
            s = Storage(Path(d)/'db')
            old = s.start({})
            r = s.start({})
            self.assertEqual(s.db.execute('SELECT status FROM runs WHERE id=?',(old,)).fetchone()[0],'interrupted')
            s.record(r,'EV','google',error='timeout')
            self.assertEqual(s.finish(r)['errors'],1)
            s.close()

class HttpTests(unittest.TestCase):
    def client(self, responses, retries=2):
        self.calls = []
        self.waits = []
        def opener(req, timeout):
            self.calls.append(req.full_url)
            value = responses.pop(0)
            if isinstance(value,Exception):
                raise value
            return io.BytesIO(value)
        return HttpClient(5,25,retries,opener,self.waits.append,lambda:0)
    def test_pacing(self):
        c = self.client([b'a',b'b'])
        c.fetch('https://example.com/a')
        c.fetch('https://example.com/b')
        self.assertEqual(self.waits,[0,5])
    def test_retry_after(self):
        err = HTTPError('https://example.com',429,'limited',{'Retry-After':'17'},None)
        c = self.client([err,b'ok'])
        self.assertEqual(c.fetch('https://example.com'),b'ok')
        self.assertEqual(self.waits,[0,17])
    def test_timeout_exhaustion_and_forbidden(self):
        c = self.client([URLError('timeout')]*3)
        with self.assertRaises(FetchError):
            c.fetch('https://example.com')
        self.assertEqual(len(self.calls),3)
        c = self.client([HTTPError('x',403,'forbidden',{},None)])
        with self.assertRaises(FetchError):
            c.fetch('https://example.com')
        self.assertEqual(len(self.calls),1)
    def test_robots_denied(self):
        c = self.client([b'User-agent: *\nDisallow: /rss\n'])
        c.check_robots()
        with self.assertRaises(FetchError):
            c.fetch('https://news.google.com/rss/search?q=x')
        self.assertEqual(len(self.calls),1)
    def test_size_limit(self):
        c = self.client([b'x'*5_000_001])
        with self.assertRaises(FetchError):
            c.fetch('https://example.com')

class CollectionTests(unittest.TestCase):
    def test_partial_failure_continues(self):
        class Client:
            def check_robots(self): pass
            def fetch(self,url):
                if 'q=bad+' in url: raise FetchError('timeout')
                return RSS
        with tempfile.TemporaryDirectory() as d:
            result = collect({'keywords':['bad','good'],'lookback_days':7},Path(d)/'db',Client())
            self.assertEqual(result,dict(fetched=1,inserted=1,duplicates=0,errors=1))
    def test_config_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config.json'
            p.write_text(json.dumps({'keywords':[]}))
            with self.assertRaises(ValueError):
                load_config(p)



class PersistenceTests(unittest.TestCase):
    def test_backup(self):
        from carmgz.backup import backup
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d)/'source.db', Path(d)/'backup.db'
            s = Storage(source)
            a = GoogleNews().parse(RSS)[0]
            r = s.start({})
            s.record(r,'EV','google',[a])
            s.finish(r)
            backup(source,target)
            db = sqlite3.connect(target)
            self.assertEqual(db.execute('SELECT count(*) FROM articles').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            db.close()
            with self.assertRaises(FileExistsError):
                backup(source,target)
            s.close()
    def test_process_lock(self):
        from carmgz.locking import collector_lock
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'db'
            with collector_lock(p):
                with self.assertRaises(RuntimeError):
                    with collector_lock(p):
                        self.fail('lock was not exclusive')
            with collector_lock(p):
                pass
    def test_policy_failure_recorded(self):
        class Client:
            def check_robots(self): raise FetchError('blocked')
            def fetch(self,url): raise AssertionError('must not request RSS')
        with tempfile.TemporaryDirectory() as d:
            result = collect({'keywords':['EV'],'lookback_days':7},Path(d)/'db',Client())
            self.assertEqual(result,dict(fetched=0,inserted=0,duplicates=0,errors=1))
    def test_missing_fields(self):
        rss = b'<rss><channel><item><title>Title</title><link>https://example.com/a</link></item></channel></rss>'
        a = GoogleNews().parse(rss)[0]
        self.assertIsNone(a.published_at)
        self.assertEqual(a.publisher,'')
        self.assertEqual(identity(a),identity(replace(a,url='https://example.com/a?tracking=x')))

if __name__ == '__main__':
    unittest.main()

