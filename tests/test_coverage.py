"""Synthetic fixtures only: evidence, uncertainty, wiring, cache and retention."""
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest

from carmgz.coverage import Checker, compare, own_url, parse_search, verify_issues
from carmgz.operations import run, track, enrich
from carmgz.analysis import analyze
from carmgz.relevance import automotive_terms
from carmgz.rss import matching_keywords
from carmgz.providers import Article
from carmgz.retention import prune
from test_operations import seed, NOW, SOURCE, CFG


def issue(title='현대차 발리 전기버스 11대 공급', at=NOW):
    return dict(id='fixture', importance_score=25, articles=[dict(title=title,published_at=at.isoformat())])


class FakeChecker:
    deadline = float('inf')
    def __init__(self): self.calls=[]
    def check(self, item, at):
        self.calls.append(item['id'])
        return dict(status='보도 완료', checked_at=at.isoformat(), search_success=True,
                    matches=[], queries=['가상 검색어'], reason='가상 사건 검증', date_limit=None)


class CoverageTests(unittest.TestCase):
    def test_domain_alias_and_lookalike(self):
        self.assertEqual(own_url('http://carmgz.kr/news/a'), 'https://www.carmgz.kr/news/a')
        for url in ('https://carmgz.kr.evil.test/a','javascript:alert(1)','https://carmgz.kr:443/a'):
            with self.assertRaises(ValueError): own_url(url)

    def test_search_ignores_sidebar_and_keeps_old_articles(self):
        html='''<article id="section-list"><a href="/news/articleView.html?idxno=1">old</a></article>
        <a href="/news/articleView.html?idxno=2">sidebar</a><script>params['total'] = "1";</script>'''
        urls,total=parse_search(html.encode())
        self.assertEqual(total,1);self.assertEqual(urls,['https://www.carmgz.kr/news/articleView.html?idxno=1'])

    def test_layout_change_fails_closed(self):
        with self.assertRaises(ValueError): parse_search(b'<html>no results</html>')

    def test_zero_results_never_means_uncovered(self):
        class Client:
            def fetch(self,url):
                assert 'sc_sdate' not in url and 'sc_edate' not in url
                return b'''<article id="section-list"></article><script>params['total']="0";</script>'''
        result=Checker({},Client()).check(issue(),NOW)
        self.assertTrue(result['search_success']);self.assertEqual(result['status'],'확인 불가')
        self.assertIsNone(result['date_limit'])

    def test_failure_never_means_uncovered(self):
        class Client:
            def fetch(self,url): raise TimeoutError('fixture')
        r=Checker({},Client()).check(issue(),NOW)
        self.assertFalse(r['search_success']);self.assertEqual(r['status'],'확인 불가')

    def test_same_company_is_not_same_event(self):
        a=dict(title='현대차 인도네시아 공장 투자',published_at=NOW.isoformat())
        self.assertNotEqual(compare(issue(),a)[0],'보도 완료')

    def test_event_time_and_numbers_guard(self):
        a=dict(title='현대차 발리 전기버스 11대 공급',published_at=NOW.isoformat())
        self.assertEqual(compare(issue(),a)[0],'보도 완료')
        self.assertNotEqual(compare(issue('현대차 발리 전기버스 50대 공급'),a)[0],'보도 완료')
        a['published_at']=(NOW-timedelta(days=200)).isoformat()
        self.assertNotEqual(compare(issue(),a)[0],'보도 완료')
        a.update(title='현대차 발리 전기버스 공급',published_at=NOW.isoformat(),_content='이번 사업에서 11대 공급')
        self.assertNotEqual(compare(issue('현대차 발리 전기버스 50대 공급'),a)[0],'보도 완료')
        a.update(title='현대차 발리 전기버스 화재')
        self.assertNotEqual(compare(issue(),a)[0],'보도 완료')

    def test_material_change_is_followup_not_rewording(self):
        a=dict(title='현대차 발리 전기버스 11대 공급 발표',published_at=(NOW-timedelta(days=4)).isoformat())
        self.assertEqual(compare(issue('현대차 발리 전기버스 공급 계획 변경'),a)[0],'후속 보도 검토')
        self.assertNotEqual(compare(issue('현대차 발리 전기버스 공급 발표'),a)[0],'후속 보도 검토')

    def test_cache_new_facts_and_briefing_force(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db');report=enrich(analyze(Path(d)/'db',[SOURCE],NOW),NOW)
            track(s.db,report,NOW);checker=FakeChecker()
            verify_issues(s.db,report,NOW,{},checker=checker)
            verify_issues(s.db,report,NOW,{},checker=checker)
            self.assertEqual(len(checker.calls),1)
            report['issues'][0]['articles'][0]['title']+=' 계획 변경'
            verify_issues(s.db,report,NOW,{},checker=checker)
            verify_issues(s.db,report,NOW,{},force=True,checker=checker)
            self.assertEqual(len(checker.calls),3)
            s.db.commit();prune(s.db,NOW+timedelta(days=8))
            self.assertEqual(s.db.execute('SELECT count(*) FROM carmgz_checks').fetchone()[0],0)
            s.close()

    def test_actual_operation_path_briefing_and_rank_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path);s.close();checker=FakeChecker()
            # PM creates snapshots with coverage; no actual network in this fixture.
            from unittest.mock import patch
            with patch('carmgz.operations.collect_publishers'):
                out=run(CFG,path,[SOURCE],Path(d)/'site','pm',NOW,coverage_checker=checker)
            self.assertTrue(checker.calls)
            self.assertEqual(out['issues'][0]['carmgz']['status'],'보도 완료')
            self.assertTrue(out['briefings'])
            entry=next(iter(out['briefings'][0]['entries'].values()))
            self.assertEqual(entry['carmgz']['status'],'보도 완료')
            baseline=run(dict(CFG,coverage=False),path,[SOURCE],Path(d)/'site','refresh',NOW)
            self.assertEqual(out['rankings'],baseline['rankings'])
            self.assertEqual(out['issues'][0]['importance_score'],baseline['issues'][0]['importance_score'])

    def test_brand_recall_and_hunger_ambiguity(self):
        for title in ('BMW X5 신차 출시','MINI 고객 축제','마세라티 그레칼레 출시','지커 7X 인도','한국타이어 독일 평가'):
            self.assertTrue(automotive_terms(title),title)
            self.assertTrue(matching_keywords(Article(title,'가상',None,'https://example.org/a','a'),['기아']),title)
        self.assertFalse(matching_keywords(Article('기아대책 후원','가상',None,'https://example.org/a','a'),['기아']))
        self.assertFalse(automotive_terms('유전자 GMOS 연구'))
        self.assertFalse(automotive_terms('애플 iPad MINI 공개'))
        self.assertFalse(automotive_terms('GM 작물 재배 연구'))
        self.assertTrue(automotive_terms('기아 문제 차량 리콜 발표'))
        for title in ('MINI 래핑카 공개','MINI 랠리 성능','GM 메리바라 회장 발표','GM 미래차 협력'):
            self.assertTrue(automotive_terms(title))

    def test_foundation_boundary_and_specific_event_grouping(self):
        from carmgz.analysis import classify, same_event
        self.assertEqual(classify(dict(publisher='가상',title='현대차 정몽구 재단 온소 클럽 출범'))[0],'review')
        a=dict(title='한국타이어 윈터 아이셉트 에보4 독일 겨울 타이어 1위',published_at=NOW.isoformat())
        b=dict(title='한국타이어 윈터 아이셉트 에보4 獨 겨울타이어 평가 1위',published_at=NOW.isoformat())
        self.assertEqual(same_event(a,b)[0],'winter-evo4')
        self.assertIsNone(same_event(a,dict(b,title='한국타이어 봄 타이어 독일 판매 1위')))

    def test_expanded_registry_feed_reaches_collector_and_storage(self):
        from carmgz.multi import collect_publishers, load_sources
        source=next(s for s in load_sources('publishers.json') if s['id']=='autoherald')
        class Client:
            evidence=[];policy_result='allowed'
            def __init__(self,*args): pass
            def fetch(self,url):
                if url!=source['feed_url']: raise AssertionError(url)
                return f'<rss><channel><item><title>BMW X5 공개</title><link>https://example.org/new</link><pubDate>{NOW.isoformat()}</pubDate></item></channel></rss>'.encode()
        with tempfile.TemporaryDirectory() as d:
            result=collect_publishers(CFG,Path(d)/'db',[source],client_factory=Client)
            self.assertEqual(result['inserted'],1)

    def test_registry_has_no_fake_active_or_excluded_collectors(self):
        sources=json.loads(Path('publishers.json').read_text(encoding='utf-8'))
        self.assertEqual(len({s['id'] for s in sources}),len(sources))
        self.assertEqual(sum(s['status']!='EXCLUDED' for s in sources),120)
        self.assertNotIn('carmgz',{s['id'] for s in sources})
        for s in sources:
            if s['status']=='ACTIVE':
                self.assertTrue(s['enabled']);self.assertTrue(s['verification']['parsed'])
            if s['id'] in ('motorgraph','toprider','carguy','autoview'):
                self.assertFalse(s['enabled'])


if __name__=='__main__': unittest.main()
