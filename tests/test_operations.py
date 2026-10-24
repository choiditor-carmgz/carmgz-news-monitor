"""Synthetic-only lifecycle, schedules, briefing and persistence regression tests."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from carmgz.analysis import analyze, same_event
from carmgz.backup import backup
from carmgz.multi_storage import MultiStorage
from carmgz.operations import alerts, briefing, enrich, run, track
from carmgz.providers import Article
from carmgz.retention import migrate, prune
from carmgz.schedule import KST, slots
from scripts.actions_state import unpack, rotate, restore

NOW = datetime.now(timezone.utc).replace(microsecond=0)
SOURCE = dict(id='test',publisher='가상 테스트 매체',feed_url='https://example.org/rss',
              rss_status='test_fixture',permission='test_fixture',enabled=True)
CFG = dict(keywords=['현대차','전기차'],interval_seconds=2,timeout_seconds=1,retries=0,lookback_days=7,data_kind='synthetic_fixture')


def seed(path, date=None, title='현대차 발리 전기버스 11대 공급'):
    s = MultiStorage(path); migrate(s.db); s.register([SOURCE]); rid=s.start({})
    s.save_articles(rid,SOURCE,[Article(title,SOURCE['publisher'],date or (NOW-timedelta(hours=1)).isoformat(), 'https://example.org/a','a')],['현대차'])
    s.finish(rid)
    return s


def issue(n=5, publishers=5, previous=2):
    return dict(id='stable',publishers_3h=publishers,volume_3h=n,previous_3h=previous,
                growth_ratio_3h=n/previous if previous else None,
                articles=[dict(title='현대차 전기차 공급',published_at=NOW.isoformat())])


class ScheduleTests(unittest.TestCase):
    def test_weekday_weekend_and_briefings(self):
        start=datetime(2026,10,19,tzinfo=KST)
        for offset in range(14):
            a=start+timedelta(days=offset); b=a+timedelta(days=1)-timedelta(microseconds=1)
            due=slots(a-timedelta(microseconds=1),b)
            collect=[t.astimezone(KST).strftime('%H:%M') for t,k in due if k=='collect']
            weekday=a.weekday()<5
            self.assertEqual(collect,[f'{h:02}:15' for h in (range(1,24,2) if weekday else (0,6,12,18))])
            self.assertEqual([t.astimezone(KST).strftime('%H:%M') for t,k in due if k=='am'], ['09:00'] if weekday else [])
            self.assertEqual([t.astimezone(KST).strftime('%H:%M') for t,k in due if k=='pm'], ['17:00'])

    def test_utc_workflow_cron_matches_schedule(self):
        import re
        cron=re.findall(r"cron: '([^']+)'",Path('.github/workflows/operations.yml').read_text(encoding='utf-8'))
        def match(spec,value):
            return spec=='*' or any(value in range(int(part.split('-')[0]),int(part.split('-')[-1])+1) if '-' in part else value==int(part) for part in spec.split(','))
        start=datetime(2026,10,18,tzinfo=timezone.utc)
        expected={t for t,k in slots(start-timedelta(microseconds=1),start+timedelta(days=14)-timedelta(microseconds=1))}
        observed=set()
        for minute in range(14*24*60):
            t=start+timedelta(minutes=minute)
            for spec in cron:
                m,h,_,_,dow=spec.split()
                if match(m,t.minute) and match(h,t.hour) and match(dow,(t.weekday()+1)%7):
                    observed.add(t)
        self.assertEqual(observed,expected)


class RetentionTests(unittest.TestCase):
    def test_expiry_children_integrity_compaction_and_unknown_first_seen(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db', (NOW-timedelta(hours=168)).isoformat())
            db=s.db; aid=db.execute('SELECT id FROM articles').fetchone()[0]
            old=(NOW-timedelta(hours=169)).isoformat()
            with db:
                db.execute('INSERT INTO article_metrics(article_id,observed_at,source,views) VALUES(?,?,?,?)',(aid,old,'test_fixture',2))
                db.execute('INSERT INTO article_annotations(article_id,created_at,method) VALUES(?,?,?)',(aid,old,'fixture'))
                db.execute('INSERT INTO article_revisions(article_id,observed_at,title) VALUES(?,?,?)',(aid,old,'TEST_EXPIRED_TITLE'))
                db.execute('INSERT INTO issues VALUES(?,?,?)',('i','TEST_EXPIRED_TITLE',old))
                db.execute('INSERT INTO issue_articles VALUES(?,?,?,?)',('i',aid,'fixture',old))
                db.execute('INSERT INTO alert_candidates(issue_id,created_at,facts_hash,reasons) VALUES(?,?,?,?)',('i',old,'f','[]'))
                db.execute('INSERT INTO operation_errors(created_at,phase,message) VALUES(?,?,?)',(old,'test','TEST_EXPIRED_TITLE'))
                db.execute('INSERT INTO briefings VALUES(?,?,?,?)',('old','pm',old,json.dumps({'expires_at':NOW.isoformat(),'secret':'TEST_EXPIRED_TITLE'})))
            self.assertEqual(prune(db,NOW),1)
            for table in ('articles','article_sources','article_keywords','article_metrics','article_annotations','article_revisions','article_fingerprints','issue_articles','issues','alert_candidates','operation_errors','briefings'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            s.close()
            self.assertNotIn(b'TEST_EXPIRED_TITLE',(Path(d)/'db').read_bytes())

    def test_recent_boundary_and_no_extension_by_last_seen(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db',(NOW-timedelta(hours=167,minutes=59)).isoformat())
            self.assertEqual(prune(s.db,NOW),0)
            with s.db:
                s.db.execute('UPDATE articles SET published_at=NULL,first_collected_at=?,last_seen_at=?',((NOW-timedelta(hours=169)).isoformat(),NOW.isoformat()))
            self.assertEqual(prune(s.db,NOW),1)
            s.close()

    def test_rss_revision_cannot_extend_original_publication(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db',(NOW-timedelta(hours=167)).isoformat())
            rid=s.start({})
            s.save_articles(rid,SOURCE,[Article('현대차 발리 전기버스 수정',SOURCE['publisher'],NOW.isoformat(),'https://example.org/a','a')],['현대차'])
            self.assertEqual(prune(s.db,NOW+timedelta(hours=2)),1)
            s.close()


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE issues(id TEXT PRIMARY KEY)');self.db.execute('CREATE TABLE schema_version(version INTEGER PRIMARY KEY)');migrate(self.db)
        self.db.execute("INSERT INTO issues VALUES('stable')")
    def tearDown(self): self.db.close()
    def test_each_condition_independent_and_small_sample_guard(self):
        self.assertEqual(len(alerts(self.db,[issue(n=1,publishers=5,previous=0)],NOW)),1)
        self.db.execute('DELETE FROM alert_candidates')
        self.assertEqual(len(alerts(self.db,[issue(n=6,publishers=1,previous=3)],NOW)),1)
        self.db.execute('DELETE FROM alert_candidates')
        self.assertEqual(alerts(self.db,[issue(n=2,publishers=1,previous=1)],NOW),[])
        i=issue(n=1,publishers=1,previous=0);i['articles'][0]['title']='현대차 대규모 리콜 10만대 발표'
        self.assertEqual(len(alerts(self.db,[i],NOW)),1)
    def test_cooldown_verified_fact_and_three_hour_boundary(self):
        self.assertEqual(len(alerts(self.db,[issue()],NOW)),1)
        self.assertEqual(alerts(self.db,[issue()],NOW+timedelta(hours=2)),[])
        self.assertEqual(len(alerts(self.db,[issue()],NOW+timedelta(hours=2),{'stable':'editor-verified-fact-1'})),1)
        self.assertEqual(alerts(self.db,[issue()],NOW+timedelta(hours=2,minutes=1),{'stable':'editor-verified-fact-1'}),[])
        self.assertEqual(len(alerts(self.db,[issue()],NOW+timedelta(hours=5))),1)
        self.assertEqual(self.db.execute('SELECT DISTINCT delivery_status FROM alert_candidates').fetchall(),[('channel_not_connected',)])


class RuntimeTests(unittest.TestCase):
    class Client:
        def __init__(self,*args): self.evidence=[];self.policy_result='allowed'
        def fetch(self,url):
            return f'<rss><channel><item><title>현대차 전기차 공급</title><link>https://example.org/new</link><pubDate>{NOW.isoformat()}</pubDate><guid>new</guid></item><item><title>현대차 날짜 없음</title><link>https://example.org/unknown</link></item></channel></rss>'.encode()
    def test_restart_new_runner_backup_and_no_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';out=Path(d)/'site'
            first=run(CFG,path,[SOURCE],out,'collect',NOW,self.Client)
            self.assertEqual(len(first['articles']),1)
            backup(path,Path(d)/'next-runner.db')
            second=run(CFG,Path(d)/'next-runner.db',[SOURCE],out,'collect',NOW+timedelta(hours=2),self.Client)
            self.assertEqual(len(second['articles']),1)
            self.assertEqual(first['issues'][0]['id'],second['issues'][0]['id'])
            self.assertEqual(second['last_collection_at'],(NOW+timedelta(hours=2)).isoformat())
            with closing(sqlite3.connect(Path(d)/'next-runner.db')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM article_sources').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT count(*) FROM article_keywords').fetchone()[0],2)
            self.assertTrue((out/'index.html').exists())
            self.assertEqual(json.loads((out/'dashboard.json').read_text(encoding='utf-8'))['data_kind'],'synthetic_fixture')

    def test_issue_stability_followup_and_no_topic_merge(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db');s.close()
            first=run(CFG,Path(d)/'db',[SOURCE],Path(d)/'site','refresh',NOW)
            s=MultiStorage(Path(d)/'db');rid=s.start({})
            s.save_articles(rid,SOURCE,[Article('현대차 발리 전기버스 충전 후속','매체B',NOW.isoformat(),'https://example.org/followup','b')],['현대차']);s.finish(rid);s.close()
            second=run(CFG,Path(d)/'db',[SOURCE],Path(d)/'site','refresh',NOW)
            self.assertEqual(first['issues'][0]['id'],second['issues'][0]['id'])
            self.assertEqual(second['issues'][0]['independent_publishers'],2)
            a=dict(title='GM 2028년 자율주행 확대',published_at=NOW.isoformat())
            for title in ('GM 2028년 자율주행 대규모 리콜','GM 2030년 자율주행 확대'):
                self.assertIsNone(same_event(a,dict(a,title=title)))

    def test_failed_collection_preserves_last_success(self):
        class Failed(self.Client):
            def fetch(self,url): raise RuntimeError('synthetic fixture failure')
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';out=Path(d)/'site'
            first=run(CFG,path,[SOURCE],out,'collect',NOW,self.Client)
            second=run(CFG,path,[SOURCE],out,'collect',NOW+timedelta(hours=2),Failed)
            self.assertEqual(second['last_collection_at'],first['last_collection_at'])
            self.assertNotEqual(second['last_attempt_at'],first['last_attempt_at'])
            self.assertEqual(second['publishers'][0]['status'],'failed')
            self.assertTrue(second['errors'])

    def test_old_rss_cannot_reenter_and_restart_retains_seven_days(self):
        class Old(self.Client):
            def fetch(self,url):
                published=(NOW-timedelta(hours=169)).isoformat()
                return f'<rss><channel><item><title>현대차 만료 테스트</title><link>https://example.org/old</link><pubDate>{published}</pubDate></item></channel></rss>'.encode()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';out=Path(d)/'site'
            result=run(CFG,path,[SOURCE],out,'collect',NOW,Old)
            self.assertEqual(result['articles'],[])
            result=run(CFG,path,[SOURCE],out,'collect',NOW+timedelta(hours=1),Old)
            self.assertEqual(result['articles'],[])
            s=seed(Path(d)/'retained',(NOW-timedelta(hours=167)).isoformat());s.close()
            backup(Path(d)/'retained',Path(d)/'new-runner')
            result=run(CFG,Path(d)/'new-runner',[SOURCE],out,'refresh',NOW)
            self.assertEqual(len(result['articles']),1)
            result=run(CFG,Path(d)/'new-runner',[SOURCE],out,'refresh',NOW+timedelta(hours=2))
            self.assertEqual(result['articles'],[])

    def test_briefings_latest_data_dedup_weekend_and_empty_db(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db');db=s.db
            report=enrich(analyze(Path(d)/'db',[SOURCE],NOW),NOW)
            with db:
                track(db,report,NOW)
                monday=datetime(2026,10,19,9,tzinfo=KST)
                generated=datetime(2026,10,25,18,tzinfo=KST)
                b=briefing(db,report,'am',monday,generated,None)
                self.assertIsNotNone(b)
                self.assertIsNone(briefing(db,report,'am',monday,generated,None))
                self.assertIsNone(briefing(db,report,'am',datetime(2026,10,24,9,tzinfo=KST),generated,None))
                self.assertIsNotNone(briefing(db,report,'pm',datetime(2026,10,24,17,tzinfo=KST),generated,None))
                self.assertIsNone(briefing(db,report,'pm',datetime(2026,10,26,17,tzinfo=KST),generated,None))
            s.close()
            empty=run(CFG,Path(d)/'empty',[SOURCE],Path(d)/'site','refresh',NOW)
            self.assertEqual(empty['articles'],[])

    def test_briefing_ranks_window_before_limiting_ten(self):
        with tempfile.TemporaryDirectory() as d:
            s=seed(Path(d)/'db',NOW.isoformat());rid=s.start({})
            for n in range(12):
                s.save_articles(rid,SOURCE,[Article(f'현대차 독립 사건 fixture {n}',SOURCE['publisher'],NOW.isoformat(),f'https://example.org/fixture/{n}',str(n))],['현대차'])
            s.finish(rid)
            report=enrich(analyze(Path(d)/'db',[SOURCE],NOW),NOW)
            # Global top ten is deliberately empty: window rankings must be independent.
            report['rankings']={'spread':[],'rising':[],'industry':[]}
            with s.db:
                track(s.db,report,NOW)
                b=briefing(s.db,report,'pm',NOW,NOW,None)
            self.assertEqual(len(b['rankings']['spread']),10)
            self.assertEqual(len(b['rankings']['industry']),10)
            self.assertEqual(len(b['rankings']['major']),10)
            self.assertTrue(b['entries'])
            s.close()

    def test_cli_backs_up_existing_database_before_first_expiry(self):
        from carmgz.operations import main
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path,(NOW-timedelta(hours=169)).isoformat())
            with s.db:
                for table in ('alert_candidates','briefings','operation_errors','operation_state'):
                    s.db.execute('DROP TABLE '+table)
            s.close()
            sources=Path(d)/'sources.json';sources.write_text(json.dumps([SOURCE]),encoding='utf-8')
            config=Path(d)/'config.json';config.write_text(json.dumps(dict(CFG,publishers=str(sources))),encoding='utf-8')
            args=['operations','--database',str(path),'--config',str(config),'--output',str(Path(d)/'site'),'--mode','refresh']
            with patch('sys.argv',args),patch('sys.stdout',new_callable=io.StringIO): main()
            backups=list(Path(d).glob('db.pre-operations-*'))
            self.assertEqual(len(backups),1)
            with closing(sqlite3.connect(backups[0])) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM articles').fetchone()[0],1)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM articles').fetchone()[0],0)


class ArtifactTests(unittest.TestCase):
    def test_unpack_integrity_and_reject_paths(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path);s.close()
            content=io.BytesIO()
            with zipfile.ZipFile(content,'w') as z:z.writestr('news.sqlite3',path.read_bytes())
            unpack(content.getvalue(),Path(d)/'restored')
            self.assertEqual(path.read_bytes(),(Path(d)/'restored').read_bytes())
            bad=io.BytesIO()
            with zipfile.ZipFile(bad,'w') as z:z.writestr('../news.sqlite3',b'bad')
            with self.assertRaises(ValueError):unpack(bad.getvalue(),Path(d)/'bad')
    def test_rotation_never_deletes_without_new_snapshot(self):
        env={'GITHUB_RUN_ID':'5','GITHUB_RUN_ATTEMPT':'1'}
        old=dict(name='carmgz-state-4-1',id=4,expired=False)
        new=dict(name='carmgz-state-5-1',id=5,expired=False)
        with patch.dict('os.environ',env),patch('scripts.actions_state.artifacts',return_value=[old]),patch('scripts.actions_state.api') as api:
            with self.assertRaises(RuntimeError):rotate()
            api.assert_not_called()
        older=dict(name='carmgz-state-3-1',id=3,expired=False,created_at='2026-10-23T00:00:00Z')
        old['created_at']='2026-10-24T00:00:00Z'
        with patch.dict('os.environ',env),patch('scripts.actions_state.artifacts',return_value=[old,new]),patch('scripts.actions_state.api') as api:
            rotate();api.assert_not_called()  # the previous snapshot stays as a fallback
        with patch.dict('os.environ',env),patch('scripts.actions_state.artifacts',return_value=[older,old,new]),patch('scripts.actions_state.api') as api:
            rotate();api.assert_called_once_with('actions/artifacts/3','DELETE')
    def test_damaged_latest_state_falls_back_to_previous_and_never_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path);s.close()
            good=io.BytesIO()
            with zipfile.ZipFile(good,'w') as z:z.writestr('news.sqlite3',path.read_bytes())
            bad=io.BytesIO()
            with zipfile.ZipFile(bad,'w') as z:z.writestr('news.sqlite3',b'not a database')
            latest=dict(name='carmgz-state-9-1',id=9,expired=False,created_at='2026-10-24T09:00:00Z',workflow_run={'id':9})
            previous=dict(name='carmgz-state-8-1',id=8,expired=False,created_at='2026-10-24T07:00:00Z',workflow_run={'id':8})
            run={'head_branch':'main','path':'.github/workflows/operations.yml','event':'schedule'}
            blobs={9:bad.getvalue(),8:good.getvalue()}
            with patch.dict('os.environ',{'STATE_BRANCH':'main'}),patch('scripts.actions_state.artifacts',return_value=[latest,previous]),\
                 patch('scripts.actions_state.api',return_value=run),patch('scripts.actions_state.download',side_effect=lambda a:blobs[a['id']]):
                restore(Path(d)/'restored')
            self.assertEqual((Path(d)/'restored').read_bytes(),path.read_bytes())
            with patch.dict('os.environ',{'STATE_BRANCH':'main'}),patch('scripts.actions_state.artifacts',return_value=[latest]),\
                 patch('scripts.actions_state.api',return_value=run),patch('scripts.actions_state.download',return_value=bad.getvalue()):
                with self.assertRaises(RuntimeError):restore(Path(d)/'empty',allow_empty=True)
            self.assertFalse((Path(d)/'empty').exists())
    def test_missing_state_fails_closed(self):
        with patch('scripts.actions_state.artifacts',return_value=[]):
            with self.assertRaises(RuntimeError):restore('unused')
            restore('unused',allow_empty=True)
