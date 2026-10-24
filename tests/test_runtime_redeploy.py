from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
import os
import unittest
from unittest.mock import patch
from scripts.select_dashboard_artifact import main
from scripts.inspect_cloudflare_runtime import binding_flags


class RuntimeRedeployTests(unittest.TestCase):
    def test_redeploy_only_accepts_successful_main_operations_snapshot(self):
        base = {'head_branch':'main','conclusion':'success','path':'.github/workflows/operations.yml'}
        env = {'SOURCE_RUN_ID':'123','GITHUB_REPOSITORY':'test/repo','GH_TOKEN':'synthetic-secret'}
        with patch.dict(os.environ, env), redirect_stdout(StringIO()):
            for override in [{}, {'head_branch':'other'}, {'conclusion':'failure'}, {'path':'.github/workflows/tests.yml'}]:
                with patch('urllib.request.urlopen',return_value=BytesIO(json.dumps(dict(base,**override)).encode())):
                    if override:
                        with self.assertRaises(ValueError):main()
                    else:main()
            with patch.dict(os.environ, {'SOURCE_RUN_ID':'123/other'}), patch('urllib.request.urlopen') as opened:
                with self.assertRaises(ValueError):main()
                opened.assert_not_called()

    def test_runtime_binding_metadata_never_contains_values(self):
        flags = binding_flags({'env_vars':{
            'CF_ACCESS_TEAM_DOMAIN':{'type':'secret_text','value':'do-not-print'},
            'CF_ACCESS_AUD':{'type':'secret_text','value':'do-not-print'},
        }})
        self.assertEqual(flags['CF_ACCESS_TEAM_DOMAIN'],{'present':True,'secret':True})
        self.assertNotIn('do-not-print',json.dumps(flags))
        self.assertFalse(binding_flags(None)['CF_ACCESS_AUD']['present'])
