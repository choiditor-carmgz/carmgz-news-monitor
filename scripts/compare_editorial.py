"""Offline comparison on a disposable SQLite copy. Never collects RSS or calls search.

Use a trusted baseline Git revision. Detailed real-data outputs belong in ignored logs/,
never in site/, web/, Cloudflare deployment bundles or committed fixtures.
"""
import argparse
from contextlib import redirect_stdout, closing
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import io
import json
import re
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import types
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from carmgz.analysis import analyze, timestamp, build_issues
from carmgz.coverage import verify_issues, RULE_VERSION
from carmgz.editorial import facts, rank
from carmgz.operations import run


def historical(ref, name):
    source=subprocess.run(['git','show',ref+':carmgz/'+name+'.py'],check=True,capture_output=True,text=True,encoding='utf-8').stdout
    module=types.ModuleType('carmgz._before_'+name)
    module.__package__='carmgz'
    exec(compile(source,ref+':'+name,'exec'),module.__dict__)
    return module


class NoHTTPChecker:
    """Count scheduling decisions only; synthetic success is not a live-search result."""
    deadline=float('inf')
    circuit_open=False
    def __init__(self):self.calls=[]
    def check(self, issue, at):
        self.calls.append(issue['id'])
        return dict(status='확인 불가',rule_version=RULE_VERSION,checked_at=at.isoformat(),search_success=True,
                    search_outcome='empty',matches=[],queries=[],searches=[],errors=[],reason='OFFLINE STUB; NOT LIVE SEARCH')


def major_before(report,at):
    from carmgz.schedule import KST
    today=at.astimezone(KST).date()
    rows=[i for i in report['issues'] if any(timestamp(a['published_at']) and
          timestamp(a['published_at']).astimezone(KST).date()==today for a in i['articles'])]
    return sorted(rows,key=lambda i:(-i['importance_score'],-i['volume_24h'],-i['independent_publishers'],i['id']))[:10]


def plans(report,fn,at):
    report=deepcopy(report)
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE issues(id TEXT PRIMARY KEY)')
        db.executemany('INSERT INTO issues VALUES(?)',[(i['id'],) for i in report['issues']])
        checker=NoHTTPChecker()
        fn(db,report,at,{},checker=checker)
        cold=len(checker.calls)
        fn(db,report,at+timedelta(hours=8),{},force=True,checker=checker)
        return dict(cold_issue_checks=cold,unchanged_after_8h_checks=len(checker.calls)-cold,live_http_requests=0)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True)
    p.add_argument('--baseline-ref',default='2173d86')
    p.add_argument('--output',default='logs/editorial-evaluation')
    args=p.parse_args()
    source=Path(args.database).resolve();output=Path(args.output).resolve()
    repo=Path(__file__).resolve().parents[1]
    for private_assets in ('site','web','cloudflare-dist'):
        if output==repo/private_assets or repo/private_assets in output.parents:
            p.error('Real-data evaluations must not be written into deployed asset directories')
    output.mkdir(parents=True,exist_ok=True)
    before_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db:
        at=datetime.fromisoformat(json.loads(db.execute("SELECT value FROM operation_state WHERE key='last_tick'").fetchone()[0]))
    sources=json.loads(Path('publishers.json').read_text(encoding='utf-8-sig'))
    cfg=json.loads(Path('config.json').read_text(encoding='utf-8-sig'))
    old=historical(args.baseline_ref,'analysis')
    old_ops=historical(args.baseline_ref,'operations');old_ops.analyze=old.analyze
    old_cov=historical(args.baseline_ref,'coverage')
    before=old.analyze(source,sources,at);after=analyze(source,sources,at)
    old_top=major_before(before,at);new_top=after['rankings']['major']
    timings={}
    for label,fn in [('before',old.analyze),('after',analyze)]:
        values=[]
        for _ in range(5):
            facts.cache_clear()
            start=time.perf_counter();fn(source,sources,at);values.append(time.perf_counter()-start)
        timings[label+'_analysis_median_seconds']=round(statistics.median(values),4)
    for label,fn,coverage_module in [('before',old_ops.run,old_cov),('after',run,None)]:
        values=[]
        for attempt in range(3):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);database=root/'news.sqlite3';shutil.copyfile(source,database)
                checker=NoHTTPChecker();facts.cache_clear()
                def forbidden(*a,**kw):raise AssertionError('Offline comparison must not collect RSS')
                start=time.perf_counter()
                with redirect_stdout(io.StringIO()):
                    if coverage_module:
                        with patch.dict(sys.modules,{'carmgz.coverage':coverage_module}):
                            payload=fn(cfg,database,sources,root/'site','refresh',at,forbidden,checker)
                    else:
                        payload=fn(cfg,database,sources,root/'site','refresh',at,forbidden,checker)
                values.append(time.perf_counter()-start)
                timings[label+'_refresh_json_bytes']=(root/'site/dashboard.json').stat().st_size
                timings[label+'_restored_snapshot_issue_checks']=len(checker.calls)
                if label=='after' and attempt==0:
                    shutil.copytree(root/'site',output/'preview',dirs_exist_ok=True)
        timings[label+'_offline_refresh_median_seconds']=round(statistics.median(values),4)
    comparison=[dict(rank=n+1,before=i['label'] if i else None,before_score=i['importance_score'] if i else None,
                     after=j['label'] if j else None,after_score=j['importance_score'] if j else None,
                     after_reasons=j.get('selection_reasons') if j else None)
                for n,(i,j) in enumerate(zip(old_top+[None]*(10-len(old_top)),new_top+[None]*(10-len(new_top))))]
    result=dict(baseline_ref=args.baseline_ref,as_of=at.isoformat(),source_sha256=before_hash,
        stored_articles=before['stored_articles'],before_issues=len(before['issues']),after_issues=len(after['issues']),
        before_classification=before['classification_counts'],after_classification=after['classification_counts'],
        timings=timings,search_plans_before=plans(before,old_cov.verify_issues,at),
        search_plans_after=plans(after,verify_issues,at),top10=comparison,
        limitations=['Offline timings exclude RSS, HTTP search and Cloudflare deployment; stub success is NOT live search success',
                      'The baseline is original main; new UI label/weight changes are not comparable numerical scales'])
    cases=[]
    patterns={'tariff':r'관세.*볼보|볼보.*관세','restructuring':r'볼보.*7400.*2500',
              'production':r'스텔란티스.*B10.*양산','recall':r'토요타.*3만대.*리콜',
              'technology':r'GM.*2028.*자율주행','new_market':r'중국산 승용차 수입 12만대'}
    for category,pattern in patterns.items():
        item=next((a for a in before['articles'] if re.search(pattern,a['title'])),None)
        if not item:continue
        cutoff=timestamp(item['first_collected_at'])+timedelta(seconds=1)
        permitted=[a['id'] for a in before['articles'] if timestamp(a['first_collected_at'])<=cutoff and
                   (timestamp(a['published_at']) is None or timestamp(a['published_at'])<=cutoff)]
        permitted=set(permitted)
        old_report=dict(issues=old.build_issues([a for a in before['articles'] if a['id'] in permitted and a['classification']=='relevant'],cutoff))
        new_issues=build_issues([a for a in after['articles'] if a['id'] in permitted and a['classification']=='relevant'],cutoff)
        find=lambda top:next((n for n,i in enumerate(top,1) if any(a['id']==item['id'] for a in i['articles'])),None)
        cases.append(dict(category=category,title=item['title'],published_at=item['published_at'],
            first_collected_at=item['first_collected_at'],
            publication_to_collection_minutes=round((timestamp(item['first_collected_at'])-timestamp(item['published_at'])).total_seconds()/60,2) if timestamp(item['published_at']) else None,
            before_rank_at_first_collection=find(major_before(old_report,cutoff)),
            after_rank_at_first_collection=find(rank(new_issues)),
            comparison='Retrospective replay using only then-published AND then-collected retained articles; not recorded historical rankings'))
    result['first_collection_cases']=cases
    assert before_hash==hashlib.sha256(source.read_bytes()).hexdigest(),'Source DB changed'
    (output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    table=['|순위|변경 전 기본 TOP 10|변경 후 취재 가치 TOP 10|점수|','|---|---|---|---:|']
    table += [f"|{r['rank']}|{(r['before'] or '').replace('|','/')}|{(r['after'] or '').replace('|','/')}|{r['after_score']}|" for r in comparison]
    (output/'comparison.md').write_text('\n'.join(table)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('top10','source_sha256')},ensure_ascii=True))


if __name__=='__main__':main()
