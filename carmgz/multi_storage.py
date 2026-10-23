"""Additive schema migration and publisher-local deduplication."""
import hashlib
import json
from .storage import Storage, now
from .rss import canonical_url, normalized_title

class MultiStorage(Storage):
    def __init__(self,path):
        super().__init__(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS publishers(id TEXT PRIMARY KEY, config_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feed_checks(
          id INTEGER PRIMARY KEY,run_id INTEGER REFERENCES runs(id),publisher_id TEXT REFERENCES publishers(id),
          checked_at TEXT NOT NULL,status TEXT NOT NULL,http_status INTEGER,parsed INTEGER NOT NULL,
          fetched INTEGER NOT NULL,relevant INTEGER NOT NULL,error TEXT,evidence_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS article_revisions(
          id INTEGER PRIMARY KEY,article_id TEXT REFERENCES articles(id),observed_at TEXT NOT NULL,
          title TEXT,published_at TEXT,url TEXT);
        CREATE TABLE IF NOT EXISTS article_relations(
          article_id TEXT REFERENCES articles(id),related_id TEXT REFERENCES articles(id),
          method TEXT NOT NULL,score REAL NOT NULL,observed_at TEXT NOT NULL,
          PRIMARY KEY(article_id,related_id,method));
        CREATE TABLE IF NOT EXISTS article_fingerprints(
          article_id TEXT PRIMARY KEY REFERENCES articles(id),publisher TEXT NOT NULL,
          title_key TEXT NOT NULL,canonical_url TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_title ON article_fingerprints(title_key);
        CREATE INDEX IF NOT EXISTS idx_fingerprints_url ON article_fingerprints(publisher,canonical_url);
        CREATE TABLE IF NOT EXISTS issues(id TEXT PRIMARY KEY,label TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS issue_articles(
          issue_id TEXT REFERENCES issues(id),article_id TEXT REFERENCES articles(id),
          method TEXT NOT NULL,assigned_at TEXT NOT NULL,PRIMARY KEY(issue_id,article_id));
        INSERT OR IGNORE INTO schema_version VALUES(2);
        ''')
        self.db.commit()
    def register(self,sources):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO publishers VALUES(?,?)',
                [(s['id'],json.dumps(s,ensure_ascii=False)) for s in sources])
            for aid,title,publisher,url in self.db.execute('SELECT id,title,publisher,url FROM articles').fetchall():
                self.db.execute('INSERT OR IGNORE INTO article_fingerprints VALUES(?,?,?,?)',
                    (aid,publisher,normalized_title(title),canonical_url(url)))
    def save_articles(self,run,source,articles,keywords):
        from .rss import matching_keywords
        stamp=now()
        inserted=0
        with self.db:
            for a in articles:
                key=normalized_title(a.title)
                row=self.db.execute('SELECT article_id FROM article_sources WHERE provider=? AND source_id=?',
                                    (source['id'],a.source_id)).fetchone()
                if not row:
                    row=self.db.execute('''SELECT f.article_id FROM article_fingerprints f JOIN articles a ON a.id=f.article_id
                        WHERE f.publisher=? AND (f.canonical_url=? OR (f.title_key=? AND
                        abs(julianday(a.published_at)-julianday(?)) <= 2)) LIMIT 1''',
                        (a.publisher,canonical_url(a.url),key,a.published_at)).fetchone()
                aid=row[0] if row else hashlib.sha256((a.publisher+'\x1f'+canonical_url(a.url)).encode()).hexdigest()
                old=self.db.execute('SELECT title,published_at,url FROM articles WHERE id=?',(aid,)).fetchone()
                if old:
                    # Retention uses the earliest known publication time, not revised RSS dates.
                    if old[1] and a.published_at:
                        from .analysis import timestamp
                        if timestamp(old[1]) and timestamp(a.published_at) and timestamp(old[1]) < timestamp(a.published_at):
                            from dataclasses import replace
                            a=replace(a,published_at=old[1])
                    if tuple(old)!=(a.title,a.published_at,a.url):
                        self.db.execute('INSERT INTO article_revisions(article_id,observed_at,title,published_at,url) VALUES(?,?,?,?,?)',
                                        (aid,stamp,*old))
                    self.db.execute('UPDATE articles SET title=?,published_at=?,url=?,last_seen_at=? WHERE id=?',
                                    (a.title,a.published_at,a.url,stamp,aid))
                else:
                    self.db.execute('INSERT INTO articles VALUES(?,?,?,?,?,?,?)',
                                    (aid,a.title,a.publisher,a.published_at,a.url,stamp,stamp))
                    inserted+=1
                self.db.execute('INSERT OR IGNORE INTO article_sources VALUES(?,?,?,?)',(source['id'],a.source_id,aid,a.url))
                self.db.execute('INSERT OR REPLACE INTO article_fingerprints VALUES(?,?,?,?)',(aid,a.publisher,key,canonical_url(a.url)))
                for keyword in matching_keywords(a,keywords):
                    self.db.execute('''INSERT INTO article_keywords VALUES(?,?,?,?) ON CONFLICT(article_id,keyword)
                                     DO UPDATE SET last_seen_at=excluded.last_seen_at''',(aid,keyword,stamp,stamp))
                # Cross-publisher exact title similarity is evidence, never a merge or asserted syndication.
                for other, in self.db.execute('SELECT article_id FROM article_fingerprints WHERE title_key=? AND publisher!=?',(key,a.publisher)).fetchall():
                    left,right=sorted((aid,other))
                    self.db.execute('INSERT OR IGNORE INTO article_relations VALUES(?,?,?,?,?)',
                                    (left,right,'normalized_title_equal_unconfirmed',1.0,stamp))
            self.db.execute('''INSERT INTO query_results(run_id,keyword,checked_at,fetched,inserted,duplicates,error)
                             VALUES(?,?,?,?,?,?,NULL)''',(run,source['id'],stamp,len(articles),inserted,len(articles)-inserted))
        return inserted
    def check(self,run,source,result):
        with self.db:
            self.db.execute('''INSERT INTO feed_checks(run_id,publisher_id,checked_at,status,http_status,parsed,fetched,relevant,error,evidence_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',(run,source['id'],now(),result['status'],result['http_status'],result['parsed'],
                result['fetched'],result['relevant'],result['error'],json.dumps(result['requests'],ensure_ascii=False)))
