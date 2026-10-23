"""168-hour lifecycle with explicit child deletion and physical compaction."""
import json
from datetime import timedelta
from .analysis import timestamp


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS operation_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS briefings(
      slot TEXT PRIMARY KEY,kind TEXT NOT NULL,generated_at TEXT NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS alert_candidates(
      id INTEGER PRIMARY KEY,issue_id TEXT NOT NULL REFERENCES issues(id),
      created_at TEXT NOT NULL,facts_hash TEXT NOT NULL,reasons TEXT NOT NULL,
      delivery_status TEXT NOT NULL DEFAULT 'channel_not_connected');
    CREATE TABLE IF NOT EXISTS operation_errors(
      id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,phase TEXT NOT NULL,message TEXT NOT NULL);
    INSERT OR IGNORE INTO schema_version VALUES(3);
    ''')
    db.commit()
    from .coverage import migrate as coverage_migrate
    coverage_migrate(db)
    db.commit()


def prune(db, at, compact=True):
    """Unknown/invalid publication time expires from FIRST collection, never last seen."""
    cutoff = at-timedelta(hours=168)
    db.execute('PRAGMA secure_delete=ON')
    expired = []
    for aid, published, first in db.execute('SELECT id,published_at,first_collected_at FROM articles'):
        effective = timestamp(published) or timestamp(first)
        if effective is None or effective <= cutoff:
            expired.append((aid,))
    with db:
        db.execute('CREATE TEMP TABLE IF NOT EXISTS expired_articles(id TEXT PRIMARY KEY)')
        db.execute('DELETE FROM expired_articles')
        db.executemany('INSERT INTO expired_articles VALUES(?)', expired)
        for table in ('article_sources', 'article_keywords', 'article_metrics', 'article_annotations',
                      'article_revisions', 'article_fingerprints', 'issue_articles'):
            db.execute(f'DELETE FROM {table} WHERE article_id IN (SELECT id FROM expired_articles)')
        db.execute('DELETE FROM article_relations WHERE article_id IN (SELECT id FROM expired_articles) OR related_id IN (SELECT id FROM expired_articles)')
        db.execute('DELETE FROM articles WHERE id IN (SELECT id FROM expired_articles)')
        for table, field in [('article_metrics', 'observed_at'), ('article_annotations', 'created_at'),
                             ('article_revisions', 'observed_at'), ('article_relations', 'observed_at'),
                             ('query_results', 'checked_at'), ('feed_checks', 'checked_at'),
                             ('operation_errors', 'created_at'), ('alert_candidates', 'created_at')]:
            db.execute(f'DELETE FROM {table} WHERE julianday({field}) IS NULL OR julianday({field})<=julianday(?)', (cutoff.isoformat(),))
        db.execute('DELETE FROM runs WHERE julianday(started_at)<=julianday(?) AND id NOT IN (SELECT run_id FROM feed_checks UNION SELECT run_id FROM query_results)', (cutoff.isoformat(),))
        db.execute('DELETE FROM alert_candidates WHERE issue_id NOT IN (SELECT issue_id FROM issue_articles)')
        db.execute('DELETE FROM carmgz_checks WHERE issue_id NOT IN (SELECT issue_id FROM issue_articles) OR julianday(checked_at)<=julianday(?)', (cutoff.isoformat(),))
        db.execute('DELETE FROM issues WHERE id NOT IN (SELECT issue_id FROM issue_articles)')
        # Embedded article data expires at the article deadline, not briefing creation + 7d.
        for slot, payload, generated in db.execute('SELECT slot,payload,generated_at FROM briefings').fetchall():
            data = json.loads(payload)
            deadline = timestamp(data.get('expires_at')) or timestamp(generated)
            if deadline is None or deadline <= at:
                db.execute('DELETE FROM briefings WHERE slot=?', (slot,))
        # Keep only live aggregate checkpoints; no article titles/URLs in state.
        for key, value in db.execute("SELECT key,value FROM operation_state WHERE key LIKE 'baseline:%'").fetchall():
            if (timestamp(json.loads(value).get('at')) or cutoff) <= cutoff:
                db.execute('DELETE FROM operation_state WHERE key=?', (key,))
    if db.execute('PRAGMA foreign_key_check').fetchall():
        raise RuntimeError('Retention foreign-key validation failed')
    if compact:
        db.execute('VACUUM')
    return len(expired)
