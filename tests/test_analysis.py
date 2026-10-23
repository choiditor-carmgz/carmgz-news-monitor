"""Synthetic fixtures only; real-data audit is reports/analysis."""
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from carmgz.analysis import classify, same_event, build_issues, analyze, export
from carmgz.multi_storage import MultiStorage
from carmgz.providers import Article

NOW = datetime(2026, 10, 23, 6, tzinfo=timezone.utc)


def article(aid='a', title='현대차 발리 전기버스 11대 공급', publisher='매체A', date='2026-10-23T05:30:00+00:00'):
    return dict(id=aid, title=title, publisher=publisher, published_at=date, url='https://example.org/'+aid)


class AnalysisTests(unittest.TestCase):
    def test_false_positive_and_exclusion(self):
        self.assertEqual(classify(article(title='기아대책 지원'))[0], 'irrelevant')
        self.assertEqual(classify(article(title='AI 바둑로봇'))[0], 'review')
        self.assertEqual(classify(article(publisher='모터그래프'))[0], 'excluded')

    def test_event_guards(self):
        a = article()
        self.assertTrue(same_event(a, article('b', publisher='매체B')))
        for b in [article(title='현대차 인니 전기버스 이동형 교실 교육'),
                  article(date='2026-10-16T00:00:00+00:00'), article(date=None),
                  article(title='현대차 발리 전기차 공급')]:
            self.assertIsNone(same_event(a, b))
        self.assertIsNone(same_event(article(title='GM 2028년 자율주행'), article(title='GM 2030년 자율주행')))

    def test_windows_growth_future_and_nulls(self):
        rows = [article(), article('b', publisher='매체B', date='2026-10-23T04:00:00+00:00'),
                article('c', date='2026-10-23T06:01:00+00:00')]
        issue = build_issues(rows, NOW)[0]
        self.assertEqual((issue['article_count'], issue['independent_publishers']), (3, 2))
        self.assertEqual((issue['volume_1h'], issue['volume_3h'], issue['volume_24h']), (1, 2, 2))
        self.assertEqual(issue['growth_per_hour'], .5)
        self.assertIsNone(issue['syndication_ratio'])
        self.assertIsNone(issue['views'])

    def test_readonly_exports_and_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'db'
            store = MultiStorage(path)
            source = dict(id='paper', publisher='매체A')
            store.register([source]); run = store.start({})
            a = article()
            store.save_articles(run, source, [Article(a['title'], a['publisher'], a['published_at'], a['url'], 'a')], ['현대차'])
            aid = store.db.execute('select id from articles').fetchone()[0]
            with store.db:
                store.db.execute('insert into article_metrics(article_id,observed_at,source,views,comments) values(?,?,?,?,?)',
                                 (aid, '2026-10-23T05:40:00+00:00', 'public-test-fixture', 0, None))
            store.finish(run); store.close()
            before = path.read_bytes()
            result = analyze(path, [source], NOW)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result['issues'][0]['views'], 0)
            self.assertIsNone(result['issues'][0]['comments'])
            export(result, Path(d)/'out')
            loaded = json.loads((Path(d)/'out/analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(loaded['stored_articles'], 1)
            self.assertTrue((Path(d)/'out/articles.csv').exists())

    def test_no_transitive_time_chain(self):
        rows = [article('a', date='2026-10-19T00:00:00+00:00'),
                article('b', date='2026-10-21T00:00:00+00:00'),
                article('c', date='2026-10-23T00:00:00+00:00')]
        self.assertEqual(len(build_issues(rows, NOW)), 2)

    def test_window_boundaries(self):
        rows = [article('a', date='2026-10-23T06:00:00+00:00'),
                article('b', date='2026-10-23T05:00:00+00:00'),
                article('c', date='2026-10-23T03:00:00+00:00'),
                article('d', date='2026-10-22T06:00:00+00:00')]
        i = build_issues(rows, NOW)[0]
        self.assertEqual((i['volume_1h'], i['volume_3h'], i['volume_24h']), (1, 2, 3))

    def test_excluded_collectors_never_fetch(self):
        from carmgz.multi import collect_publishers
        class ForbiddenClient:
            def __init__(self, *args):
                raise AssertionError('Excluded publisher must never create HTTP client')
        with tempfile.TemporaryDirectory() as d:
            sources = [dict(id=pid, publisher=name, enabled=True, feed_url='https://example.org/rss',
                            rss_status='candidate', permission='public_feed_policy_check')
                       for pid, name in [('motorgraph', '모터그래프'), ('toprider', '탑라이더'),
                                         ('carguy', '카가이'), ('autoview', '오토뷰')]]
            cfg = dict(keywords=['자동차'], interval_seconds=2, timeout_seconds=1, retries=0)
            result = collect_publishers(cfg, Path(d)/'db', sources, Path(d)/'report.json', ForbiddenClient)
            self.assertEqual(result['inserted'], 0)
            report = json.loads((Path(d)/'report.json').read_text(encoding='utf-8'))
            self.assertEqual([p['status'] for p in report['publishers']], ['excluded']*4)
