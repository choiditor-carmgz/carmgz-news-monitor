"""Synthetic release tests. No public data or real network requests."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from carmgz.analysis import analyze
from carmgz.multi import load_sources, collect_publishers
from carmgz.multi_storage import MultiStorage
from carmgz.providers import Article
from carmgz.operations import enrich, track, briefing
from scripts.actions_state import prefix, rotate, restore
from test_operations import NOW, CFG, SOURCE, seed


class ReleaseTests(unittest.TestCase):
    def test_new_publishers_retained_and_not_falsely_active(self):
        sources=load_sources('publishers.json')
        self.assertEqual(len(sources),123)
        for ident in ('3protv','sidae'):
            source=next(s for s in sources if s['id']==ident)
            self.assertFalse(source['enabled'])
            self.assertIn(source['status'],('PENDING','UNSUPPORTED'))
        era=next(s for s in sources if s['id']=='sidae')
        self.assertIn('머니S',era['aliases'])
        self.assertEqual(era['publisher'],'동행미디어 시대')
        self.assertNotIn('moneys',{s['id'] for s in sources})

    def test_unapproved_source_cannot_be_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'sources.json'
            path.write_text(json.dumps([dict(SOURCE,enabled=True,permission='contract_required')]),encoding='utf-8')
            with self.assertRaises(ValueError): load_sources(path)

    def test_held_sources_never_request_even_if_page_is_public(self):
        class Forbidden:
            def __init__(self,*args):raise AssertionError('Unapproved request')
        sources=[s for s in load_sources('publishers.json') if s['id'] in ('3protv','sidae')]
        with tempfile.TemporaryDirectory() as d,redirect_stdout(io.StringIO()):
            result=collect_publishers(CFG,Path(d)/'db',sources,client_factory=Forbidden)
            self.assertEqual(result['inserted'],0)
        from scripts.verify_publishers import verify
        with patch('scripts.verify_publishers.PolicyClient',side_effect=AssertionError('Unapproved discovery')):
            self.assertEqual(verify(next(s for s in sources if s['id']=='sidae'),['자동차'])['status'],'UNSUPPORTED')

    def test_era_aliases_count_as_one_without_rewriting_stored_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path);rid=s.start({})
            titles=['현대차 발리 전기버스 공급','현대차 발리 전기버스 11대 공급']
            for n,name in enumerate(('머니S','동행미디어 시대')):
                s.save_articles(rid,SOURCE,[Article(titles[n],name,NOW.isoformat(),f'https://example.org/{n}',str(n))],['현대차'])
            s.finish(rid)
            era=dict(id='sidae',publisher='동행미디어 시대',aliases=['머니S','시대'])
            report=analyze(path,[SOURCE,era],NOW)
            group=next(i for i in report['issues'] if any(a.get('original_publisher')=='머니S' for a in i['articles']))
            self.assertEqual(group['publishers'].count('동행미디어 시대'),1)
            self.assertEqual(s.db.execute("SELECT count(*) FROM articles WHERE publisher='머니S'").fetchone()[0],1)
            s.close()

    def test_preview_rotation_cannot_delete_production_state(self):
        with patch.dict('os.environ',{'STATE_BRANCH':'codex/test','GITHUB_RUN_ID':'5','GITHUB_RUN_ATTEMPT':'1'}):
            preview=prefix();self.assertNotEqual(preview,'carmgz-state-')
            old=dict(name=preview+'4-1',id=4,expired=False)
            new=dict(name=preview+'5-1',id=5,expired=False)
            production=dict(name='carmgz-state-3-1',id=3,expired=False)
            with patch('scripts.actions_state.artifacts',return_value=[old,new,production]),patch('scripts.actions_state.api') as api:
                rotate();api.assert_called_once_with('actions/artifacts/4','DELETE')
            with patch('scripts.actions_state.artifacts',return_value=[production]),patch('scripts.actions_state.api') as api:
                with self.assertRaises(RuntimeError):restore('unused')
                api.assert_not_called()

    def test_briefing_has_separate_coverage_lists_and_no_unverified_uncovered(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path)
            report=enrich(analyze(path,[SOURCE],NOW),NOW)
            with s.db:
                track(s.db,report,NOW)
                report['issues'][0]['carmgz']={'status':'확인 불가'}
                payload=briefing(s.db,report,'pm',NOW,NOW,None)
            self.assertEqual(payload['coverage_lists'],{'미보도':[],'후속 보도 검토':[]})
            s.close()

    def test_workflow_manual_preview_is_separate_from_pages_permissions(self):
        text=Path('.github/workflows/operations.yml').read_text(encoding='utf-8')
        self.assertIn('STATE_BRANCH: ${{ github.ref_name }}',text)
        self.assertIn('publish:',text)
        operate,deploy=text.split('\n  deploy:')
        self.assertNotIn('environment:',operate)
        self.assertIn('name: cloudflare-pages',deploy)
        self.assertIn("github.ref == 'refs/heads/main'",deploy)
        self.assertNotIn('actions/deploy-pages',text)
        self.assertNotIn('actions/upload-pages-artifact',text)
        self.assertIn('wrangler pages deploy cloudflare-dist',deploy)

    def test_private_issue_notes_and_error_details_stay_out_of_public_json(self):
        from carmgz.operations import public_payload
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';s=seed(path);report=enrich(analyze(path,[SOURCE],NOW),NOW)
            report['issues'][0]['internal_notes']='PRIVATE_FIXTURE'
            with s.db:
                s.db.execute('INSERT INTO operation_errors(created_at,phase,message) VALUES(?,?,?)',(NOW.isoformat(),'collect','PRIVATE_FIXTURE'))
            output=public_payload(s.db,report,NOW,'synthetic_fixture')
            self.assertNotIn('PRIVATE_FIXTURE',json.dumps(output))
            s.close()
