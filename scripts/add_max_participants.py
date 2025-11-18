"""One-off helper to add `max_participants` column to the `tournament` table if missing.
Run with the virtualenv Python: 
  .\.venv\Scripts\python.exe scripts\add_max_participants.py
"""
from app import create_app, db
from config import Config
import sqlite3
import os

app = create_app(Config)

def column_exists(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols

with app.app_context():
    # Flask-SQLAlchemy: use db.engine (safer across versions)
    engine = db.engine
    url = str(engine.url)
    if url.startswith('sqlite'):
        # Extract path to sqlite file
        # Example: sqlite:///C:/path/to/database/bug_arena.db
        db_path = url.split('///', 1)[-1]
        db_path = os.path.expanduser(db_path)
        print('Using sqlite DB at', db_path)
        conn = sqlite3.connect(db_path)
        try:
            if not column_exists(conn, 'tournament', 'max_participants'):
                print('Column missing — adding `max_participants`')
                conn.execute('ALTER TABLE tournament ADD COLUMN max_participants INTEGER')
                conn.commit()
                print('Column added successfully')
            else:
                print('Column already exists — nothing to do')
        finally:
            conn.close()
    else:
        # For other DBs, attempt ALTER TABLE via SQLAlchemy
        with engine.connect() as conn:
            if not engine.dialect.has_table(conn, 'tournament'):
                raise SystemExit('tournament table does not exist')
            # Best effort: try to add column (may require migration tool for production)
            try:
                conn.execute('ALTER TABLE tournament ADD COLUMN max_participants INTEGER')
                print('Executed ALTER TABLE (verify with your DB migration tool)')
            except Exception as e:
                print('Could not add column automatically:', e)
                raise

print('Done')
