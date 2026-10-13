"""DB adapter. PostgreSQL in deployment; SQLite only for local development."""
import os
import sqlite3
from pathlib import Path

PG_SCHEMA = '''
CREATE TABLE IF NOT EXISTS issues(id BIGSERIAL PRIMARY KEY, number INTEGER UNIQUE NOT NULL, pub_date TEXT NOT NULL, status TEXT DEFAULT 'draft', approved_at TEXT, approved_snapshot TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS articles(id BIGSERIAL PRIMARY KEY, issue_id BIGINT NOT NULL REFERENCES issues(id), position INTEGER NOT NULL, url TEXT NOT NULL, supplied_content TEXT DEFAULT '', source_title TEXT DEFAULT '', source_text TEXT DEFAULT '', extract_status TEXT DEFAULT 'pending', extract_notes TEXT DEFAULT '', headline TEXT DEFAULT '', body TEXT DEFAULT '', category TEXT DEFAULT 'حكومات', image_url TEXT DEFAULT '', image_asset_id TEXT DEFAULT '', image_license_status TEXT DEFAULT 'unverified', image_local TEXT DEFAULT '', revision INTEGER DEFAULT 0, UNIQUE(issue_id,position));
CREATE TABLE IF NOT EXISTS reviews(id BIGSERIAL PRIMARY KEY, issue_id BIGINT REFERENCES issues(id), article_id BIGINT REFERENCES articles(id), stage TEXT NOT NULL, revision INTEGER NOT NULL, reviewer TEXT NOT NULL, decision TEXT NOT NULL, note TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit(id BIGSERIAL PRIMARY KEY, issue_id BIGINT, article_id BIGINT, action TEXT, actor TEXT, payload TEXT DEFAULT '{}', created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS publications(id BIGSERIAL PRIMARY KEY, issue_id BIGINT REFERENCES issues(id), kind TEXT, external_id TEXT, source_snapshot TEXT, status TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS public_releases(issue_id BIGINT PRIMARY KEY REFERENCES issues(id), public_snapshot TEXT NOT NULL, released_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, released_by TEXT NOT NULL, revoked_at TIMESTAMPTZ);
CREATE INDEX IF NOT EXISTS idx_articles_issue ON articles(issue_id);
CREATE INDEX IF NOT EXISTS idx_reviews_article ON reviews(article_id, stage, revision);
'''
SQLITE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, pub_date TEXT NOT NULL, status TEXT DEFAULT 'draft', approved_at TEXT, approved_snapshot TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY, issue_id INTEGER NOT NULL REFERENCES issues(id), position INTEGER NOT NULL, url TEXT NOT NULL, supplied_content TEXT DEFAULT '', source_title TEXT DEFAULT '', source_text TEXT DEFAULT '', extract_status TEXT DEFAULT 'pending', extract_notes TEXT DEFAULT '', headline TEXT DEFAULT '', body TEXT DEFAULT '', category TEXT DEFAULT 'حكومات', image_url TEXT DEFAULT '', image_asset_id TEXT DEFAULT '', image_license_status TEXT DEFAULT 'unverified', image_local TEXT DEFAULT '', revision INTEGER DEFAULT 0, UNIQUE(issue_id,position));
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, issue_id INTEGER REFERENCES issues(id), article_id INTEGER REFERENCES articles(id), stage TEXT NOT NULL, revision INTEGER NOT NULL, reviewer TEXT NOT NULL, decision TEXT NOT NULL, note TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, issue_id INTEGER, article_id INTEGER, action TEXT, actor TEXT, payload TEXT DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS publications(id INTEGER PRIMARY KEY, issue_id INTEGER REFERENCES issues(id), kind TEXT, external_id TEXT, source_snapshot TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS public_releases(issue_id INTEGER PRIMARY KEY REFERENCES issues(id), public_snapshot TEXT NOT NULL, released_at TEXT DEFAULT CURRENT_TIMESTAMP, released_by TEXT NOT NULL, revoked_at TEXT);
'''

class PGConnection:
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row
        self.conn=psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
    def __enter__(self):return self
    def __exit__(self, et, ev, tb):
        try:
            if et:self.conn.rollback()
            else:self.conn.commit()
        finally:self.conn.close()
    def execute(self, query, args=None):
        # Existing MVP uses sqlite parameter markers; queries are static application literals.
        return self.conn.execute(query.replace('?', '%s'),args)

def database(data_dir):
    if os.getenv('DATABASE_URL'):
        return PGConnection(os.environ['DATABASE_URL'])
    if os.getenv('APP_ENV')=='production':
        raise RuntimeError('DATABASE_URL is mandatory in production')
    c=sqlite3.connect(Path(data_dir)/'newsletter.sqlite3')
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def initialize(data_dir):
    if os.getenv('DATABASE_URL'):
        with database(data_dir) as c:
            for statement in PG_SCHEMA.split(';'):
                if statement.strip():c.execute(statement)
    else:
        with database(data_dir) as c:
            c.executescript(SQLITE_SCHEMA)
            cols=[r['name'] for r in c.execute('PRAGMA table_info(articles)').fetchall()]
            if 'image_local' not in cols:c.execute("ALTER TABLE articles ADD COLUMN image_local TEXT DEFAULT ''")

# Additive migrations preserve existing issues and approval snapshots.
def migrate_workflow(data_dir):
    columns={'workflow_stage':"TEXT DEFAULT 'draft'",'owner_email':"TEXT DEFAULT ''",'reviewer_email':"TEXT DEFAULT ''",'designer_email':"TEXT DEFAULT ''",'final_email':"TEXT DEFAULT ''",'content_revision':'INTEGER DEFAULT 0','generation_error':"TEXT DEFAULT ''"}
    with database(data_dir) as c:
        if os.getenv('DATABASE_URL'):
            for name,kind in columns.items():c.execute(f'ALTER TABLE issues ADD COLUMN IF NOT EXISTS {name} {kind}')
        else:
            existing={r['name'] for r in c.execute('PRAGMA table_info(issues)').fetchall()}
            for name,kind in columns.items():
                if name not in existing:c.execute(f'ALTER TABLE issues ADD COLUMN {name} {kind}')
        c.execute("UPDATE issues SET workflow_stage='approved' WHERE status='approved'")
        c.execute('CREATE TABLE IF NOT EXISTS article_media(article_id BIGINT PRIMARY KEY REFERENCES articles(id), payload TEXT NOT NULL)')
        idkind='BIGSERIAL PRIMARY KEY' if os.getenv('DATABASE_URL') else 'INTEGER PRIMARY KEY'
        c.execute(f'CREATE TABLE IF NOT EXISTS issue_versions(id {idkind}, issue_id BIGINT NOT NULL REFERENCES issues(id), revision INTEGER NOT NULL, snapshot TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        c.execute('CREATE TABLE IF NOT EXISTS google_oauth_tokens(email TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS generated_decks(issue_id BIGINT PRIMARY KEY REFERENCES issues(id), revision INTEGER NOT NULL, payload TEXT NOT NULL)')
