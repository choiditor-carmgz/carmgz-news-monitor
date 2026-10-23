"""Synthetic Unicode fixtures; never reads or changes the real news database."""
from contextlib import redirect_stdout
import io
import json
import logging
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from carmgz.console import AsciiConsoleFormatter
from carmgz.discover import audit
from carmgz.multi import collect_publishers
from carmgz.operations import run

PUBLISHER='가상 언론사 🚗'
TITLE='현대차 전기차 출시 🚗'
SOURCE=dict(id='fixture',publisher=PUBLISHER,enabled=True,feed_url='https://example.org/rss',
            official_reference='https://example.org',rss_status='fixture',permission='fixture')
CFG=dict(keywords=['현대차','전기차'],interval_seconds=2,timeout_seconds=1,retries=0,
         lookback_days=7,data_kind='synthetic_fixture')


class Client:
    def __init__(self,*args): self.evidence=[]; self.policy_result='allowed'
    def fetch(self,url):
        return f'<rss><channel><item><title>{TITLE}</title><link>https://example.org/a</link><guid>fixture</guid></item></channel></rss>'.encode('utf-8')


class ConsoleTests(unittest.TestCase):
    def test_collector_console_is_safe_on_cp1252_ascii_and_utf8(self):
        for encoding in ('cp1252','ascii','utf-8'):
            with self.subTest(encoding=encoding),tempfile.TemporaryDirectory() as d:
                raw=io.BytesIO()
                with io.TextIOWrapper(raw,encoding=encoding,errors='strict') as stream:
                    with redirect_stdout(stream):
                        result=collect_publishers(CFG,Path(d)/'db',[SOURCE],Path(d)/'report.json',Client)
                    stream.flush()
                    output=raw.getvalue().decode('ascii')
                self.assertEqual(result['inserted'],1)
                self.assertEqual(json.loads(output)['publisher'],PUBLISHER)
                self.assertIn('\\u',output)
                # Report and DB retain original Unicode, independently of console encoding.
                report=(Path(d)/'report.json').read_text(encoding='utf-8')
                self.assertIn(PUBLISHER,report)
                with sqlite3.connect(Path(d)/'db') as db:
                    self.assertEqual(db.execute('SELECT title,publisher FROM articles').fetchone(),(TITLE,PUBLISHER))
                db.close()

    def test_cp1252_console_does_not_corrupt_dashboard_json(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';raw=io.BytesIO()
            with io.TextIOWrapper(raw,encoding='cp1252',errors='strict') as stream:
                with redirect_stdout(stream):
                    collect_publishers(CFG,path,[SOURCE],client_factory=Client)
                    run(CFG,path,[SOURCE],Path(d)/'site',mode='refresh')
            text=(Path(d)/'site/dashboard.json').read_text(encoding='utf-8')
            self.assertIn(TITLE,text)
            self.assertIn(PUBLISHER,text)
            self.assertEqual(json.loads(text)['articles'][0]['title'],TITLE)

    def test_discovery_error_console_safe_and_file_unicode_preserved(self):
        class Failed(Client):
            def fetch(self,url): raise RuntimeError('한글 접속 오류 🚗')
        with tempfile.TemporaryDirectory() as d:
            raw=io.BytesIO()
            with io.TextIOWrapper(raw,encoding='cp1252',errors='strict') as stream:
                with patch('carmgz.discover.PolicyClient',Failed),redirect_stdout(stream):
                    audit([SOURCE],str(Path(d)/'discovery.json'))
                stream.flush(); output=raw.getvalue().decode('ascii')
            self.assertIn('\\u',output)
            report=json.loads((Path(d)/'discovery.json').read_text(encoding='utf-8'))
            self.assertIn('한글 접속 오류 🚗',report[0]['error'])

    def test_console_log_escapes_unicode_file_log_preserves_it(self):
        with tempfile.TemporaryDirectory() as d:
            raw=io.BytesIO()
            with io.TextIOWrapper(raw,encoding='cp1252',errors='strict') as stream:
                console=logging.StreamHandler(stream)
                console.setFormatter(AsciiConsoleFormatter('%(levelname)s %(message)s'))
                file=logging.FileHandler(Path(d)/'log',encoding='utf-8')
                file.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
                logger=logging.getLogger('carmgz.synthetic-console-test');logger.propagate=False
                logger.handlers=[console,file];logger.setLevel(logging.INFO)
                try:
                    try: raise ValueError('한글 예외 🚗')
                    except ValueError: logger.exception('수집 오류 %s',PUBLISHER)
                    console.flush();file.flush()
                    output=raw.getvalue().decode('ascii')
                    self.assertIn('\\u',output)
                finally:
                    logger.handlers=[];file.close();console.close()
            saved=(Path(d)/'log').read_text(encoding='utf-8')
            self.assertIn('한글 예외 🚗',saved)
            self.assertIn(PUBLISHER,saved)
