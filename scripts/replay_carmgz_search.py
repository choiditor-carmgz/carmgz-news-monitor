"""Replay the real refresh path on a disposable DB copy; no RSS or deployment."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlencode, quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carmgz.coverage import Checker, load_config, parse_search, search_diagnostics
from carmgz.operations import run
from carmgz.multi import load_sources


class RecordingChecker(Checker):
    def __init__(self):
        super().__init__(load_config())
        self.checked = []

    def check(self, issue, at):
        result = super().check(issue, at)
        self.checked.append(result)
        return result


def main():
    source, output = map(Path, sys.argv[1:3])
    def forbid_collection(*args, **kwargs):
        raise AssertionError('Diagnostic replay must never collect RSS')
    checker = RecordingChecker()
    cfg = json.loads(Path('config.json').read_text(encoding='utf-8-sig'))
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        database = target/'news.sqlite3'
        shutil.copyfile(source, database)
        payload = run(cfg, database, load_sources(cfg.get('publishers','publishers.json')),
                      target/'site', mode='refresh', client_factory=forbid_collection,
                      coverage_checker=checker)
    # No snapshot, article bodies, cookies, environment, or arbitrary headers exported.
    result = dict(mode='refresh', disposable_copy=True, rss_collection=False,
                  attempted=len(checker.checked),
                  successful=sum(bool(p['search_success']) for p in checker.checked),
                  circuit_open=checker.circuit_open,
                  checks=checker.checked)
    # Controlled diagnostic comparisons, separate from the stopped operational checker.
    failed = next((s['query'] for p in checker.checked for s in p['searches'] if not s['success']), None)
    if failed:
        probe = Checker(load_config())
        variants = dict(original=urlencode(dict(sc_area='A',view_type='sm',sc_word=failed)),
                        explicit_page=urlencode(dict(sc_area='A',view_type='sm',sc_word=failed,page=1)),
                        percent_space=urlencode(dict(sc_area='A',view_type='sm',sc_word=failed),quote_via=quote),
                        default_list=urlencode(dict(sc_area='A',view_type='sm')))
        result['controlled_probes'] = []
        for name, params in variants.items():
            url = 'https://www.carmgz.kr/news/articleList.html?'+params
            row = dict(variant=name, request_url=url)
            start = len(probe.client.evidence)
            try:
                body = probe.fetch(url)
                row.update(http_status=probe.client.last_status,content_type=probe.client.last_content_type,
                           diagnostics=search_diagnostics(body, failed))
                links,total = parse_search(body)
                row.update(total=total, first_result_urls=links[:3])
                try:
                    parse_search(body, failed)
                    row['query_verified'] = True
                except ValueError:
                    row['query_verified'] = False
            except Exception as exc:
                row['error_type'] = type(exc).__name__
            row['redirect_count'] = sum(bool(e.get('location')) for e in probe.client.evidence[start:])
            result['controlled_probes'].append(row)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'}))
    return 0 if checker.checked and all(p['search_success'] for p in checker.checked) else 1


if __name__ == '__main__':
    sys.exit(main())
