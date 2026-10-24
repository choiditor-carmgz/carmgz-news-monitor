"""Synthetic behavioral regressions; real snapshot comparison is a separate report."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from carmgz.analysis import build_issues, classify, same_event, analyze
from carmgz.editorial import facts, rank, score, material_signature
from carmgz.coverage import verify_issues, display_status, RULE_VERSION
from carmgz.operations import run
from test_analysis import article, NOW
from test_operations import seed, SOURCE, CFG


def story(title, ident='a', hours=1, publisher='매체A'):
    return article(ident,title,publisher,(NOW-timedelta(hours=hours)).isoformat())


class RecordingChecker:
    deadline=float('inf')
    circuit_open=False
    def __init__(self):self.calls=[]
    def check(self,issue,at):
        self.calls.append(issue['id'])
        return dict(status='확인 불가',rule_version=RULE_VERSION,checked_at=at.isoformat(),
                    search_success=True,search_outcome='empty',errors=[],matches=[],queries=[],searches=[])


class EditorialTests(unittest.TestCase):
    def test_all_issues_scored_and_single_major_story_beats_repeated_promotion(self):
        rows=[story('BMW 신형 전기차 출시',str(n),publisher='매체'+str(n)) for n in range(25)]
        rows += [story('혼다 전기차 결함 3만대 리콜','z')]
        rows += [story('현대차 신차 '+str(n)+'번째 소식','p'+str(n)) for n in range(25)]
        issues=build_issues(rows,NOW)
        self.assertGreater(len(issues),20)
        self.assertTrue(all('score_components' in i for i in issues))
        self.assertIn('리콜',rank(issues)[0]['label'])
        promo=next(i for i in issues if i['article_count']==25)
        self.assertLessEqual(promo['score_components']['spread'],12.5)
        for i in issues:
            self.assertAlmostEqual(i['importance_score'],sum(i['score_components'].values()))
            self.assertLessEqual(i['importance_score'],100)

    def test_industry_categories_and_context_do_not_treat_brand_mentions_as_value(self):
        serious=['현대차 자동차 관세 규제 시행','완성차 관세 인하 규제 시행','볼보 3분기 적자 2500명 감원',
                 '현대차 울산 공장 신설 1조원 투자 확정','혼다 1만6,254대 리콜',
                 '현대차 레벨4 자율주행 실제 물류 상용화']
        weak=['유해란 BMW 레이디스 챔피언십 단독 선두','기아 e스포츠 대회 후원',
              '오비맥주 소주 테슬라 도전 [푸드360]']
        for title in serious:
            self.assertEqual(classify(story(title))[0],'relevant')
            self.assertGreaterEqual(build_issues([story(title)],NOW)[0]['score_components']['impact'],25)
        for title in weak:self.assertNotEqual(classify(story(title))[0],'relevant')
        self.assertLess(build_issues([story('BMW 퇴사하면 최대 10억원 보상금 제시')],NOW)[0]['score_components']['impact'],20)
        for title in ['BMW 골프 GTI 신형 출시','현대차 모터스포츠 랠리 기술 공개',
                      'BMW 골프대회서 신차 공개']:
            self.assertEqual(classify(story(title))[0],'relevant')

    def test_quantities_do_not_confuse_age_currency_or_mixed_korean_numbers(self):
        self.assertIn(('대',16254),facts('혼다 1만6,254대 리콜')['quantities'])
        self.assertNotIn(('대',30),facts('전기차 화재 30대 남성 숨져')['quantities'])
        self.assertIn(('원',1_240_000_000_000),facts('공장 투자 1조2400억원')['quantities'])
        self.assertEqual(facts('공장 투자 '+'9'*400+'원')['quantities'],())

    def test_earnings_grouping_preserves_different_quarters_and_factories(self):
        a=story('볼보 3분기 7400억 적자 2500명 감원')
        self.assertTrue(same_event(a,story('볼보 3분기 7500억원 적자','b')))
        self.assertIsNone(same_event(a,story('볼보 2분기 7400억 적자','b')))
        self.assertIsNone(same_event(story('현대차 울산 공장 신규 투자 1조원 확정'),
                                      story('현대차 아산 공장 신규 투자 1조원 확정','b')))

    def test_reprints_do_not_refresh_event_age_or_invent_material_changes(self):
        old=story('혼다 1만대 결함 리콜','a',48)
        original=build_issues([old],NOW)[0]
        repeated=build_issues([old,story(old['title'],'b',1,'매체B')],NOW)[0]
        self.assertEqual(original['effective_event_at'],repeated['effective_event_at'])
        self.assertEqual(original['score_components']['timeliness'],repeated['score_components']['timeliness'])
        self.assertEqual(material_signature(original),material_signature(repeated))
        # Differently rounded loss figures and the word 'additional' do not prove a new fact.
        i=dict(articles=[story('볼보 3분기 7500억원 적자 2500명 감원','a',24),
                         story('볼보 3분기 7400억원 적자 2500명 추가 감원','b',1)],label='볼보',id='v')
        score(i,NOW)
        self.assertEqual(i['effective_event_at'],i['articles'][0]['published_at'])

    def test_explicit_comparable_change_refreshes_old_issue_not_collection_time(self):
        rows=[story('현대차 울산 공장 투자 1조원 확정','a',48),
              story('현대차 울산 공장 투자 기존 1조원에서 2조원으로 확대','b',1)]
        issues=build_issues(rows,NOW)
        self.assertEqual(len(issues),1)
        self.assertEqual(issues[0]['effective_event_at'],rows[1]['published_at'])
        no_date=story('혼다 결함 리콜');no_date['published_at']=None
        i=build_issues([no_date],NOW)[0]
        self.assertGreater(i['score_components']['impact'],0)
        self.assertEqual(i['score_components']['timeliness'],0)

    def test_related_financial_angles_do_not_fill_top_ten_but_distinct_investment_survives(self):
        rows=[story('볼보 2500명 감원','a'),story('볼보 2000명 감원','b'),
              story('볼보 울산 공장 신설 1조원 투자 확정','c')]
        issues=build_issues(rows,NOW)
        self.assertEqual(len(issues),3)
        self.assertEqual(len(rank(issues)),2)
        self.assertTrue(any('공장' in i['label'] for i in rank(issues)))
        extra=build_issues([story('볼보 관세 인상 시행으로 적자 우려','p')],NOW)
        self.assertEqual(len(rank(issues+extra)),3)

    def test_search_is_top_ten_only_success_reused_and_does_not_change_rankings(self):
        issues=build_issues([story('현대차 '+str(n)+'번째 모델 출시',str(n)) for n in range(30)],NOW)
        top=rank(issues);report=dict(issues=issues,rankings=dict(industry=top))
        before=[i['id'] for i in rank(issues)]
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE issues(id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO issues VALUES(?)',[(i['id'],) for i in issues])
            checker=RecordingChecker()
            verify_issues(db,report,NOW,{},checker=checker)
            self.assertEqual(checker.calls,before)
            verify_issues(db,report,NOW+timedelta(hours=8),{},force=True,checker=checker)
            self.assertEqual(len(checker.calls),10)
            self.assertEqual(report['coverage_summary']['attempted_issues'],0)
        self.assertEqual([i['id'] for i in rank(issues)],before)

    def test_unchanged_legacy_success_migrates_without_an_http_check(self):
        from carmgz.coverage import migrate
        item=build_issues([story('혼다 3만대 결함 리콜')],NOW)[0]
        legacy=hashlib.sha256(json.dumps(sorted((a['title'],a['published_at']) for a in item['articles']),ensure_ascii=False).encode()).hexdigest()
        cached=dict(status='보도 완료',rule_version=RULE_VERSION,checked_at=(NOW-timedelta(days=1)).isoformat(),search_success=True,matches=[])
        with sqlite3.connect(':memory:') as db:
            migrate(db)
            db.execute('INSERT INTO carmgz_checks VALUES(?,?,?,?)',(item['id'],cached['checked_at'],legacy,json.dumps(cached)))
            checker=RecordingChecker();verify_issues(db,dict(issues=[item]),NOW,{},checker=checker)
            self.assertEqual(checker.calls,[])
            self.assertEqual(db.execute('SELECT fingerprint FROM carmgz_checks').fetchone()[0],material_signature(item))
            self.assertEqual(item['carmgz']['checked_at'],cached['checked_at'])

    def test_optional_search_initialization_failure_still_builds_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'db';store=seed(database,date=(NOW-timedelta(hours=1)).isoformat());store.close()
            with patch('carmgz.coverage.Checker',side_effect=RuntimeError('fixture')):
                payload=run(dict(CFG,data_kind='real_rss'),database,[SOURCE],Path(directory)/'site','refresh',NOW)
            self.assertTrue(payload['rankings']['major'])
            self.assertEqual(payload['issues'][0]['carmgz']['display_status'],'검색 실패')
            self.assertTrue((Path(directory)/'site/dashboard.json').exists())

    def test_failed_or_unperformed_search_never_means_uncovered(self):
        self.assertEqual(display_status({}),'검색 대기')
        self.assertEqual(display_status(dict(checked_at=NOW.isoformat(),search_success=False)),'검색 실패')
        self.assertEqual(display_status(dict(checked_at=NOW.isoformat(),search_success=True)),'검색 범위 내 미발견')

    def test_unanticipated_events_group_without_hand_written_rules(self):
        import carmgz.analysis as analysis
        with patch.object(analysis,'EVENTS',[]):
            rows=[story("마세라티코리아, 국내 단 1대 '그레칼레 크리스탈로' 출시",'a',publisher='매체A'),
                  story('마세라티 ‘그레칼레 크리스탈로’ 국내 단 1대 출시⋯330마력·제로백 5.3초','b',publisher='매체B'),
                  story('마세라티, 돌로미티 담은 그레칼레 크리스탈로 국내 한 대 한정 출시','c',publisher='매체C'),
                  story('지커, 7X 국내 인도 시작…1호 고객은 SK온','d',publisher='매체A'),
                  story('지커, SK온 1호 고객 맞이하며 7X 국내 인도 개시','e',publisher='매체B')]
            sizes=sorted(i['article_count'] for i in build_issues(rows,NOW))
            self.assertEqual(sizes,[2,3])

    def test_generic_grouping_keeps_conflicting_facts_apart(self):
        for left,right in [('현대차 발리 전기버스 11대 공급','현대차 발리 전기차 공급'),
                           ('현대차 신차 20번째 소식','현대차 신차 21번째 소식'),
                           ('한국타이어 윈터 아이셉트 에보4 독일 겨울 타이어 1위','한국타이어 봄 타이어 독일 판매 1위'),
                           ('볼보 2500명 감원 추진 발표','볼보 2000명 감원 추진 발표')]:
            self.assertIsNone(same_event(story(left),story(right,'b')),(left,right))


if __name__=='__main__':unittest.main()
