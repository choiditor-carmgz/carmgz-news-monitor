"""Offline regression tests; all tokens and API responses are synthetic."""
from contextlib import redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from scripts import check_cloudflare as cf

TOKEN = 'synthetic-secret-do-not-log'
CONFIG = {'name': cf.PROJECT, 'production_branch':'main', 'deployment_configs':{'production':{'env_vars':{
    'CF_ACCESS_TEAM_DOMAIN':{'value':'https://test.cloudflareaccess.com'},
    'CF_ACCESS_AUD':{'value':'private-binding-do-not-log'}}}}}


class Reply(BytesIO):
    code = 200
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())


def ok(result):
    return Reply({'success':True, 'result':result})


def denied(code=401):
    return HTTPError('https://api.cloudflare.com/synthetic', code, TOKEN, {},
                     BytesIO(json.dumps({'success':False,'errors':[{'code':10000,'message':TOKEN}],
                                         'result':{'secret':TOKEN}}).encode()))


class CloudflareAuthTests(unittest.TestCase):
    def run_cli(self, replies, token=TOKEN, account=cf.EXPECTED_ACCOUNT):
        out, err = StringIO(), StringIO()
        with patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN':token, 'CLOUDFLARE_ACCOUNT_ID':account}), \
             patch('urllib.request.OpenerDirector.open', side_effect=replies) as opened, \
             redirect_stdout(out), redirect_stderr(err):
            status = cf.cli()
        text = out.getvalue()+err.getvalue()
        self.assertNotIn(TOKEN,text)
        self.assertNotIn('private-binding-do-not-log',text)
        self.assertNotIn(cf.EXPECTED_ACCOUNT,text)
        return status, text, opened

    def test_exact_https_urls_bearer_and_active_user_token(self):
        status, text, opened=self.run_cli([ok({'status':'active','id':TOKEN}),ok(CONFIG)])
        self.assertEqual(status,0)
        requests=[c.args[0] for c in opened.call_args_list]
        self.assertEqual([r.full_url for r in requests],[cf.API+'/user/tokens/verify',
            cf.API+f'/accounts/{cf.EXPECTED_ACCOUNT}/pages/projects/{cf.PROJECT}'])
        for r in requests:
            self.assertEqual(r.get_header('Authorization'),'Bearer '+TOKEN)
            self.assertIsNone(r.get_header('X-auth-key'))
            self.assertIsNone(r.get_header('X-auth-email'))
            self.assertNotIn(TOKEN,r.full_url)
        self.assertIn('Pages API authentication and project lookup succeeded',text)

    def test_account_token_verification_fallback(self):
        status,text,opened=self.run_cli([denied(),ok({'status':'active'}),ok(CONFIG)])
        self.assertEqual(status,0)
        self.assertEqual(opened.call_args_list[1].args[0].full_url,
                         cf.API+f'/accounts/{cf.EXPECTED_ACCOUNT}/tokens/verify')
        self.assertIn('User token verification: HTTP 401',text)
        self.assertIn('Token verification: active',text)

    def test_active_token_does_not_prove_pages_permission(self):
        status,text,_=self.run_cli([ok({'status':'active'}),denied(403)])
        self.assertEqual(status,1)
        self.assertIn('Active token, but Pages lookup failed',text)
        self.assertNotIn('Pages API authentication and project lookup succeeded',text)

    def test_401_codes_visible_but_remote_messages_and_tracebacks_hidden(self):
        status,text,opened=self.run_cli([denied(),denied(),denied()])
        self.assertEqual(status,1)
        self.assertEqual(opened.call_count,3)
        self.assertIn('Pages project lookup: HTTP 401; error_codes=[10000]',text)
        self.assertIn('API authentication/access not confirmed',text)
        self.assertNotIn('Traceback',text)

    def test_verify_endpoint_failure_does_not_replace_actual_pages_result(self):
        status,text,_=self.run_cli([denied(),denied(),ok(CONFIG)])
        self.assertEqual(status,0)
        self.assertIn('Token verification: not confirmed',text)
        self.assertIn('Pages API authentication and project lookup succeeded',text)

    def test_malformed_inputs_never_leave_process(self):
        for token in ['',TOKEN+'\n','Bearer '+TOKEN,'"'+TOKEN+'"',TOKEN+'\u200b']:
            status,_,opened=self.run_cli([],token=token)
            self.assertEqual(status,1)
            opened.assert_not_called()
        for account in ['', 'a'*32, cf.EXPECTED_ACCOUNT+'\n']:
            status,_,opened=self.run_cli([],account=account)
            self.assertEqual(status,1)
            opened.assert_not_called()

    def test_invalid_json_network_errors_and_wrong_project_fail_safely(self):
        for replies in [
            [BytesIO(TOKEN.encode())],
            [URLError(TOKEN),URLError(TOKEN),URLError(TOKEN)],
            [ok({'status':'active'}),ok(dict(CONFIG,name='other'))],
            [ok({'status':'expired'}),ok({'status':'disabled'}),denied()],
        ]:
            status,text,_=self.run_cli(replies)
            self.assertEqual(status,1)
            self.assertNotIn('Traceback',text)

    def test_redirect_is_never_followed_with_credentials(self):
        self.assertIsNone(cf.NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))
        status,text,_=self.run_cli([denied(302),denied(302),denied(302)])
        self.assertEqual(status,1)
        self.assertIn('HTTP 302',text)

    def test_unset_cloudflare_runtime_bindings_return_specific_safe_error(self):
        for configs in [None, {'production':None}, {'production':{'env_vars':None}}]:
            status,text,_=self.run_cli([ok({'status':'active'}),ok(dict(CONFIG,deployment_configs=configs))])
            self.assertEqual(status,1)
            self.assertIn('Configure existing Access verification variable in Pages production: CF_ACCESS_TEAM_DOMAIN',text)
            self.assertNotIn('unexpected response',text)
