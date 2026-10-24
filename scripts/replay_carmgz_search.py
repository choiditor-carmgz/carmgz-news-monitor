"""Replay the real refresh path on a disposable DB copy; no RSS or deployment."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carmgz.coverage import Checker, load_config
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
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='checks'}))
    return 0 if checker.checked and all(p['search_success'] for p in checker.checked) else 1


if __name__ == '__main__':
    sys.exit(main())
