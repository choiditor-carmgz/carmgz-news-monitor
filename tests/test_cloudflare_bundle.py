import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.prepare_cloudflare import prepare
from scripts.check_cloudflare import main as check_cloudflare


class CloudflareBundleTests(unittest.TestCase):
    def test_only_allowlisted_assets_are_deployed_and_all_routes_are_guarded(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'site'
            source.mkdir()
            for name in ('index.html','app.js','style.css','_worker.js','news.sqlite3','debug.html'):
                (source/name).write_text('fixture',encoding='utf-8')
            payload=dict(data_kind='real_rss',retention_hours=168,rankings={},
                         **{k:[] for k in ('articles','issues','publishers','briefings','alerts','errors')})
            (source/'dashboard.json').write_text(json.dumps(payload),encoding='utf-8')
            target=Path(d)/'bundle'
            prepare(source,target)
            self.assertEqual({p.name for p in target.iterdir()},
                             {'index.html','app.js','style.css','dashboard.json','_worker.js','_routes.json'})
            self.assertEqual(json.loads((target/'_routes.json').read_text())['exclude'],[])
            payload['data_kind']='synthetic_fixture'
            (source/'dashboard.json').write_text(json.dumps(payload),encoding='utf-8')
            with self.assertRaises(ValueError):prepare(source,Path(d)/'rejected')

    def test_deploy_preflight_rejects_wrong_branch_and_missing_access_binding(self):
        from io import BytesIO
        config={'production_branch':'main','deployment_configs':{'production':{'env_vars':{
            'CF_ACCESS_TEAM_DOMAIN':{'value':'https://test.cloudflareaccess.com'},'CF_ACCESS_AUD':{'value':'test'}}}}}
        with patch.dict('os.environ',{'CLOUDFLARE_ACCOUNT_ID':'a'*32,'CLOUDFLARE_API_TOKEN':'synthetic'}):
            for branch,has_aud,allowed in [('main',True,True),('other',True,False),('main',False,False)]:
                config['production_branch']=branch
                config['deployment_configs']['production']['env_vars']['CF_ACCESS_AUD']={'value':'test' if has_aud else ''}
                with patch('urllib.request.urlopen',return_value=BytesIO(json.dumps({'success':True,'result':config}).encode())):
                    if allowed:check_cloudflare()
                    else:
                        with self.assertRaises(ValueError):check_cloudflare()
