"""Restore/verify/rotate a rolling SQLite artifact. Tokens stay in environment."""
import argparse
from contextlib import closing
import io
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.request
import urllib.error
import zipfile

PREFIX = 'carmgz-state-'


def branch():
    return os.environ.get('STATE_BRANCH','main')


def prefix():
    # Preview state must never replace or rotate production state.
    return PREFIX if branch()=='main' else 'carmgz-preview-'+hashlib.sha256(branch().encode()).hexdigest()[:12]+'-'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(path, method='GET'):
    repo = os.environ['GITHUB_REPOSITORY']
    url = f'https://api.github.com/repos/{repo}/{path}'
    req = urllib.request.Request(url, method=method, headers={
        'Authorization':'Bearer '+os.environ['GH_TOKEN'], 'Accept':'application/vnd.github+json',
        'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'CARMGZ-state-manager'})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=45) as response:
        body = response.read()
        return json.loads(body) if body else None


def artifacts():
    rows = []
    page = 1
    while True:
        batch = api(f'actions/artifacts?per_page=100&page={page}')['artifacts']
        rows.extend(batch)
        if len(batch) < 100:
            return rows
        page += 1


def validate(path):
    if Path(path).stat().st_size > 100_000_000:
        raise RuntimeError('State exceeds 100 MB storage budget')
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Invalid state database')
        for table in ('articles','publishers','feed_checks','operation_state','briefings','alert_candidates'):
            db.execute('SELECT 1 FROM '+table+' LIMIT 1')


def prepare(path):
    """Even failed runs must not upload a restored, unpruned old snapshot."""
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from carmgz.retention import migrate, prune
    validate(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        migrate(db)
        prune(db,datetime.now(timezone.utc))
    validate(path)


def unpack(content, destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Refusing to overwrite restored state')
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        # Never extract arbitrary paths or other files from an artifact.
        members = z.infolist()
        if len(members) != 1 or members[0].filename != 'news.sqlite3' or members[0].file_size > 100_000_000:
            raise ValueError('Unexpected state artifact layout/size')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(z.read(members[0]))
    try:
        validate(destination)
    except Exception:
        destination.unlink()
        raise


def download(artifact):
    try:
        api(f"actions/artifacts/{artifact['id']}/zip")
        raise RuntimeError('Expected signed artifact download redirect')
    except urllib.error.HTTPError as exc:
        if exc.code != 302:
            raise
        signed = exc.headers['Location']
    # Do not forward the GitHub token to signed object storage URLs.
    with urllib.request.urlopen(signed, timeout=60) as response:
        content = response.read(100_000_001)
    if len(content) > 100_000_000:
        raise ValueError('State artifact exceeds budget')
    return content


def restore(destination, allow_empty=False):
    rows = [a for a in artifacts() if a['name'].startswith(prefix())]
    corrupt = []
    for a in sorted(rows, key=lambda a:a['created_at'], reverse=True):
        if a['expired']:
            continue
        run = api('actions/runs/'+str(a['workflow_run']['id']))
        # Trust only this production workflow from the default branch.
        if run['head_branch'] != branch() or run['path'].split('@')[0] != '.github/workflows/operations.yml' or run['event'] not in ('schedule','workflow_dispatch'):
            continue
        # Auth/network errors propagate: they affect every candidate and must not look like corruption.
        content = download(a)
        try:
            unpack(content, destination)
        except (ValueError, RuntimeError, zipfile.BadZipFile, sqlite3.DatabaseError) as exc:
            # A damaged snapshot is skipped for the previous verified one; never replaced by an empty DB.
            corrupt.append(a['name'])
            print(f"Skipped damaged state {a['name']}: {type(exc).__name__}")
            continue
        print('Restored verified SQLite state'+(f' (skipped damaged: {", ".join(corrupt)})' if corrupt else ''))
        return
    if corrupt:
        raise RuntimeError('Every available state snapshot failed verification; refusing to start empty. Inspect artifacts before initialize=true.')
    if not allow_empty:
        raise RuntimeError('No valid persisted state. Explicit workflow_dispatch initialize=true is required; never silently reset.')
    print('Explicit empty-state initialization requested')


def rotate():
    rows = artifacts()
    current = [a for a in rows if a['name'] == prefix()+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT'] and not a['expired']]
    if len(current) != 1:
        raise RuntimeError('New state upload not confirmed; old artifacts preserved')
    # Keep the newest earlier snapshot as a fallback for a damaged latest one (1-day retention still applies).
    older = sorted((a for a in rows if a['name'].startswith(prefix()) and a['id'] != current[0]['id']),
                   key=lambda a:(a.get('created_at',''), a['id']), reverse=True)
    for a in older[1:]:
        api(f"actions/artifacts/{a['id']}", 'DELETE')
    print('Rotated state; latest and one previous snapshot retained')


def clean_pages():
    # Only this workflow's page archives, after deployment. State never uses this name.
    for a in artifacts():
        if a['name'] == 'github-pages' and str(a.get('workflow_run',{}).get('id')) == os.environ.get('GITHUB_RUN_ID'):
            api(f"actions/artifacts/{a['id']}", 'DELETE')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['restore','validate','rotate','clean-pages','namespace'])
    p.add_argument('--database', default='data/news.sqlite3')
    p.add_argument('--allow-empty', action='store_true')
    args = p.parse_args()
    if args.command == 'restore':
        restore(args.database, args.allow_empty)
    elif args.command == 'validate':
        prepare(args.database)
    elif args.command == 'rotate':
        rotate()
    elif args.command == 'clean-pages':
        clean_pages()
    else:
        print(prefix())
