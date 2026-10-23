import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .providers import identity

def now():
    return datetime.now(timezone.utc).isoformat()

class Storage:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO schema_version VALUES(1);
        CREATE TABLE IF NOT EXISTS articles(
          id TEXT PRIMARY KEY,title TEXT NOT NULL,publisher TEXT NOT NULL,published_at TEXT,
          url TEXT NOT NULL,first_collected_at TEXT NOT NULL,last_seen_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS article_sources(
          provider TEXT NOT NULL,source_id TEXT NOT NULL,article_id TEXT NOT NULL REFERENCES articles(id),
          url TEXT NOT NULL,PRIMARY KEY(provider,source_id));
        CREATE TABLE IF NOT EXISTS article_keywords(
          article_id TEXT NOT NULL REFERENCES articles(id),keyword TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,PRIMARY KEY(article_id,keyword));
        CREATE TABLE IF NOT EXISTS runs(
          id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,
          fetched INTEGER DEFAULT 0,inserted INTEGER DEFAULT 0,duplicates INTEGER DEFAULT 0,
          errors INTEGER DEFAULT 0,config_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS query_results(
          id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES runs(id),keyword TEXT NOT NULL,
          checked_at TEXT NOT NULL,fetched INTEGER NOT NULL,inserted INTEGER NOT NULL,
          duplicates INTEGER NOT NULL,error TEXT);
        CREATE TABLE IF NOT EXISTS article_metrics(
          id INTEGER PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),
          observed_at TEXT NOT NULL,source TEXT NOT NULL,views INTEGER,comments INTEGER);
        CREATE TABLE IF NOT EXISTS article_annotations(
          id INTEGER PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),
          created_at TEXT NOT NULL,method TEXT NOT NULL,issue_category TEXT,
          importance_score REAL,metadata_json TEXT);
        CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(published_at);
        """)
        self.db.commit()
    def start(self, config):
        with self.db:
            self.db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
            return self.db.execute('INSERT INTO runs(started_at,status,config_json) VALUES(?,?,?)',
                (now(),'running',json.dumps(config,ensure_ascii=False))).lastrowid
    def record(self, run, keyword, provider, articles=(), error=None):
        stamp = now()
        inserted = 0
        with self.db:
            for a in articles:
                row = self.db.execute('SELECT article_id FROM article_sources WHERE provider=? AND source_id=?',
                    (provider,a.source_id)).fetchone()
                aid = row[0] if row else identity(a)
                inserted += self.db.execute('INSERT OR IGNORE INTO articles VALUES(?,?,?,?,?,?,?)',
                    (aid,a.title,a.publisher,a.published_at,a.url,stamp,stamp)).rowcount
                self.db.execute('UPDATE articles SET last_seen_at=? WHERE id=?',(stamp,aid))
                self.db.execute('INSERT OR IGNORE INTO article_sources VALUES(?,?,?,?)',(provider,a.source_id,aid,a.url))
                self.db.execute("""INSERT INTO article_keywords VALUES(?,?,?,?)
                    ON CONFLICT(article_id,keyword) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
                    (aid,keyword,stamp,stamp))
            self.db.execute("""INSERT INTO query_results(run_id,keyword,checked_at,fetched,inserted,duplicates,error)
                VALUES(?,?,?,?,?,?,?)""",(run,keyword,stamp,len(articles),inserted,len(articles)-inserted,error))
    def finish(self, run):
        counts = self.db.execute("""SELECT coalesce(sum(fetched),0),coalesce(sum(inserted),0),
            coalesce(sum(duplicates),0),count(error) FROM query_results WHERE run_id=?""",(run,)).fetchone()
        with self.db:
            self.db.execute("""UPDATE runs SET finished_at=?,status=?,fetched=?,inserted=?,duplicates=?,errors=?
                WHERE id=?""",(now(),'partial_failure' if counts[3] else 'success',*counts,run))
        return dict(zip(('fetched','inserted','duplicates','errors'),counts))
    def close(self):
        self.db.close()
