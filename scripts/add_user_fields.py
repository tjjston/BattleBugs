"""One-off helper to add missing user management columns to the SQLite database.
Run with the virtualenv Python:
  .\.venv\Scripts\python.exe scripts\add_user_fields.py

This script will add:
- role (VARCHAR)
- elo (INTEGER)
- is_active (BOOLEAN)
- is_banned (BOOLEAN)
- warnings/comments counters

This mirrors the pattern used by other helper scripts in `scripts/`.
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
    engine = db.engine
    url = str(engine.url)
    if url.startswith('sqlite'):
        db_path = url.split('///', 1)[-1]
        db_path = os.path.expanduser(db_path)
        print('Using sqlite DB at', db_path)
        conn = sqlite3.connect(db_path)
        try:
            additions = [
                ('role', "ALTER TABLE user ADD COLUMN role VARCHAR(20) DEFAULT 'USER'"),
                ('elo', "ALTER TABLE user ADD COLUMN elo INTEGER DEFAULT 1000"),
                ('is_active', "ALTER TABLE user ADD COLUMN is_active INTEGER DEFAULT 1"),
                ('is_banned', "ALTER TABLE user ADD COLUMN is_banned INTEGER DEFAULT 0"),
                ('warnings', "ALTER TABLE user ADD COLUMN warnings INTEGER DEFAULT 0"),
                ('comments_made', "ALTER TABLE user ADD COLUMN comments_made INTEGER DEFAULT 0"),
            ]

            for col, stmt in additions:
                if not column_exists(conn, 'user', col):
                    print(f'Adding column `{col}`')
                    try:
                        conn.execute(stmt)
                        conn.commit()
                        print(f'`{col}` added')
                    except Exception as e:
                        print('Failed to add', col, e)
                else:
                    print(f'`{col}` already exists')
        finally:
            conn.close()
    else:
        # Attempt via SQLAlchemy for other DBs
        with engine.connect() as conn:
            try:
                conn.execute("ALTER TABLE user ADD COLUMN role VARCHAR(20)")
            except Exception as e:
                print('Could not add role via SQLAlchemy:', e)

print('Done')
