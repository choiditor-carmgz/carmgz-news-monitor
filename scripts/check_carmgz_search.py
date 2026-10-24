"""Opt-in live official-search regression; metadata only, no monitor DB or RSS run."""
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from carmgz.coverage import Checker, load_config, parse_article, parse_search

CASES = [
    ('마이홈차저', '22736'),
    ('2027 쏘나타 디 엣지', '22826'),
    ('모빌리티 플레이그라운드', '22969'),
    ('오토살롱테크, 참가기업 확정', '22817'),
    ('15년간 개발한 BMS', '11834'),
]


def main():
    checker = Checker(load_config())
    rows = []
    for query, identifier in CASES + [('CARMGZNORESULT20261024XYZ', None)]:
        url = 'https://www.carmgz.kr/news/articleList.html?'+urlencode(dict(sc_area='A',view_type='sm',sc_word=query))
        row = {'query': query, 'expected_id': identifier, 'success': False}
        if checker.circuit_open:
            row['search_outcome'] = 'deferred'
            rows.append(row)
            continue
        body = None
        phase = 'search'
        try:
            body = checker.fetch(url)
            row['http_status'] = checker.client.last_status
            urls, total = parse_search(body, query=query)
            checker.same_search_failures = 0
            checker.last_search_failure = None
            checker.search_cache[query] = (urls,total)
            checker.search_metadata[query] = dict(http_status=row['http_status'],response_url=url)
            row.update(search_success=True, total=total, returned=len(urls),
                       expected_found=any('idxno='+str(identifier) in u for u in urls) if identifier else total==0)
            if identifier and row['expected_found']:
                phase = 'article'
                expected_url = next(u for u in urls if 'idxno='+identifier in u)
                article = parse_article(checker.fetch(expected_url), expected_url)
                checker.article_cache[expected_url] = article
                row['article'] = {k:v for k,v in article.items() if not k.startswith('_')}
                checked = checker.check({'id':'live-'+identifier,'importance_score':0,
                                         'articles':[row['article']]},datetime.now(timezone.utc))
                row['production_check'] = dict(search_success=checked['search_success'],
                    search_outcome=checked.get('search_outcome'),status=checked['status'],
                    expected_match=any(m['url']==expected_url for m in checked['matches']))
            row['success'] = row['expected_found']
        except Exception as exc:
            row.update(error=type(exc).__name__+': '+str(exc))
            if phase == 'search':
                row['error_code'] = checker.search_failure(exc)
            # Diagnostic only: distinguish a genuinely unapplied query from network errors.
            if body is not None:
                import re
                row['echo'] = re.findall(r'''params\[['"]sc_word['"]\]\s*=\s*(['"])(.*?)\1''',body.decode('utf-8-sig', errors='replace'),re.S)
        rows.append(row)
    result = {'cases': rows, 'positive_successes': sum(r['success'] for r in rows if r['expected_id']),
              'production_matches': sum(r.get('production_check',{}).get('expected_match',False) for r in rows),
              'positive_cases': len(CASES), 'zero_result_success': rows[-1]['success'],
              'elapsed_seconds': round(load_config()['max_seconds']-(checker.deadline-time.monotonic()),2),
              'redirects': [e for e in checker.client.evidence if e.get('location')]}
    print(json.dumps(result, ensure_ascii=True))
    if len(sys.argv)>1:
        Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['positive_successes']==len(CASES) and result['production_matches']==len(CASES) and result['zero_result_success'] else 1


if __name__ == '__main__':
    sys.exit(main())
