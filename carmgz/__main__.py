import argparse
import json
import logging
from pathlib import Path
from .http import HttpClient
from .providers import GoogleNews
from .storage import Storage
from .locking import collector_lock

def load_config(path):
    cfg = json.loads(path.read_text(encoding='utf-8-sig'))
    words = cfg.get('keywords')
    if not isinstance(words,list) or not words or any(not isinstance(w,str) or not w.strip() for w in words):
        raise ValueError('keywords must be a nonempty string list')
    cfg['keywords'] = list(dict.fromkeys(w.strip() for w in words))
    for key, low, high in [('interval_seconds',2,3600),('timeout_seconds',1,120),
                           ('retries',0,5),('lookback_days',1,365)]:
        value = cfg[key]
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not low <= value <= high:
            raise ValueError(f'{key} must be in [{low}, {high}]')
    if not isinstance(cfg['retries'],int) or not isinstance(cfg['lookback_days'],int):
        raise ValueError('retries and lookback_days must be integers')
    if not isinstance(cfg.get('database'),str) or not cfg['database'].strip():
        raise ValueError('database path required')
    return cfg

def collect(cfg, db_path, client=None, provider=None):
    with collector_lock(db_path):
        return _collect(cfg, db_path, client, provider)

def _collect(cfg, db_path, client=None, provider=None):
    client = client or HttpClient(cfg['interval_seconds'],cfg['timeout_seconds'],cfg['retries'])
    provider = provider or GoogleNews(cfg['lookback_days'])
    store = Storage(db_path)
    run = store.start(cfg)
    try:
        try:
            client.check_robots()
        except Exception as exc:
            logging.error('robots policy unavailable: %s',exc)
            store.record(run,'__robots__',provider.name,error=str(exc))
            return store.finish(run)
        for keyword in cfg['keywords']:
            try:
                articles = provider.parse(client.fetch(provider.url(keyword)))
            except Exception as exc:
                logging.exception('Failed keyword=%s',keyword)
                store.record(run,keyword,provider.name,error=f'{type(exc).__name__}: {exc}')
                continue
            store.record(run,keyword,provider.name,articles)
            logging.info('keyword=%s fetched=%d',keyword,len(articles))
        return store.finish(run)
    finally:
        store.close()

def main():
    parser = argparse.ArgumentParser(description='CARMGZ multi-publisher RSS collector')
    parser.add_argument('--config',type=Path,default=Path('config.json'))
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except (ValueError,KeyError,OSError) as exc:
        parser.error(str(exc))
    base = args.config.resolve().parent
    (base/'logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.StreamHandler(),logging.FileHandler(base/'logs'/'collector.log',encoding='utf-8')])
    try:
        from .multi import collect_publishers, load_sources
        result = collect_publishers(cfg,base/cfg['database'],load_sources(base/cfg.get('publishers','publishers.json')),base/cfg.get('report','reports/latest.json'))
    except ValueError as exc:
        parser.error(str(exc))
    except (RuntimeError, OSError) as exc:
        logging.error('%s',exc)
        return 1
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result['errors'] else 0

if __name__ == '__main__':
    raise SystemExit(main())

