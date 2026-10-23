"""Validate and stage only dashboard assets; never upload SQLite or diagnostic files."""
import json
from pathlib import Path
import shutil


def prepare(source='site', target='cloudflare-dist'):
    source, target = Path(source), Path(target)
    payload = json.loads((source/'dashboard.json').read_text(encoding='utf-8'))
    if payload['data_kind'] != 'real_rss' or payload['retention_hours'] != 168:
        raise ValueError('Production requires real RSS and 168-hour retention')
    for field in ('articles', 'issues', 'publishers', 'briefings', 'alerts', 'errors'):
        if not isinstance(payload[field], list):
            raise ValueError('Invalid dashboard schema: '+field)
    if not isinstance(payload['rankings'], dict):
        raise ValueError('Invalid rankings')
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError('Staging directory must be empty')
    for name in ('index.html', 'app.js', 'style.css', 'dashboard.json', '_worker.js'):
        shutil.copyfile(source/name, target/name)
    (target/'_routes.json').write_text(json.dumps({'version': 1, 'include': ['/*'], 'exclude': []}), encoding='utf-8')
    print(f'Cloudflare bundle: {len(payload["articles"])} real articles, {len(payload["issues"])} issues')


if __name__ == '__main__':
    prepare()
