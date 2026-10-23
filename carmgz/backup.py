"""Consistent SQLite backup for future persistent-storage upload."""
import argparse
from pathlib import Path
import sqlite3

def backup(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('Backup must use a different path')
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError('Refusing to overwrite existing backup')
    target.parent.mkdir(parents=True,exist_ok=True)
    src = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed')
    finally:
        dst.close()
        src.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source')
    p.add_argument('target')
    args = p.parse_args()
    backup(args.source,args.target)
