import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request

from scripts.search_response_study import StudyClient, header_facts, plan, study, main


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.interval = 2
        self.evidence = []
        self.last_status = 200
        self.last_content_type = 'text/html'
        self.response_facts = {}
        self.stop_requested = False
        self.wire_requests = 0
        self.limit = 20
        self.budget_seconds = 180
        self.deadline = time.monotonic()+180
        self.starts = []

    def fetch(self, url):
        self.wire_requests += 1
        self.starts.append(time.monotonic())
        self.evidence.append(dict(final_url=url))
        query = parse_qs(urlsplit(url).query)['sc_word'][0]
        echo = "params['sc_word']="+json.dumps(query)+';' if next(self.outcomes) else ''
        return ('<article id="section-list"></article><script>'+echo+"params['total']='0';</script>").encode()


class ResponseStudyTests(unittest.TestCase):
    def test_completed_diagnostic_with_invalid_response_is_not_a_green_health_check(self):
        result = dict(stop_reason='plan_completed',rows=[dict(valid=False)])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'facts.json'
            with patch('scripts.search_response_study.study',return_value=result), \
                 patch('scripts.search_response_study.StudyClient'), \
                 patch.dict('os.environ',{'FOCUS_QUERY':'','STUDY_ORDER':'spacing'}), \
                 patch('sys.argv',['study',str(output)]):
                self.assertEqual(main(),1)
            self.assertFalse(json.loads(output.read_text(encoding='utf-8'))['rows'][0]['valid'])

    def test_header_allowlist_never_serializes_arbitrary_values(self):
        facts = header_facts({'Age':'123','Date':'Sat, 24 Oct 2026 05:00:00 GMT',
            'Cache-Control':'private="PRIVATE", max-age=60', 'X-Cache':'HIT node=PRIVATE',
            'Server':'PRIVATE','Set-Cookie':'PRIVATE','Authorization':'PRIVATE',
            'X-Served-By':'PRIVATE','ETag':'PRIVATE','X-Cache-Key':'PRIVATE'})
        self.assertEqual(facts['age'],123)
        self.assertEqual(facts['cache_max_age'],60)
        self.assertEqual(facts['cache_markers'],['HIT'])
        self.assertNotIn('PRIVATE',json.dumps(facts))
        self.assertIsNone(header_facts({})['age'])

    def test_two_invalid_responses_get_only_one_delayed_same_query_retry(self):
        cases = plan('fixture')
        result = study(FakeClient([False,False,False]),cases)
        self.assertEqual(len(result['rows']),3)
        self.assertTrue(result['rows'][-1]['delayed_retry'])
        self.assertEqual(result['rows'][-1]['query'],result['rows'][-2]['query'])
        self.assertGreaterEqual(result['rows'][-1]['gap'],6)
        self.assertEqual(result['outcomes'],{'invalid':3})
        self.assertNotEqual(result['stop_reason'],'plan_completed')

    def test_validated_delayed_recovery_is_distinct_from_http_200(self):
        result = study(FakeClient([False,False,True]),plan('fixture')[:2])
        self.assertEqual(result['outcomes'],{'invalid':2,'valid':1})
        self.assertEqual(result['stop_reason'],'plan_completed')
        self.assertEqual(result['rows'][-1]['total'],0)

    def test_wire_budget_counts_every_request_and_blocks_server_requested_stop(self):
        client = StudyClient({'max_seconds':180,'max_issues':20})
        guard = next(h for h in client.transport.__self__.handlers if type(h).__name__=='Budget')
        for _ in range(20):
            request = Request('https://www.carmgz.kr/robots.txt');request.timeout=8
            guard.https_request(request)
        with self.assertRaises(TimeoutError): guard.https_request(request)
        self.assertEqual(client.wire_requests,20)
        client = StudyClient({});client.stop_requested=True
        guard = next(h for h in client.transport.__self__.handlers if type(h).__name__=='Budget')
        with self.assertRaises(TimeoutError): guard.https_request(request)
        self.assertEqual(client.wire_requests,0)


if __name__=='__main__':
    unittest.main()
