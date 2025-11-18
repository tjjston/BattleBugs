"""One-off helper to add missing tournament columns to the SQLite database.
Run with the virtualenv Python:
  .\.venv\Scripts\python.exe scripts\add_tournament_fields.py

This mirrors the pattern used by `add_max_participants.py` and will:
- add `created_at` (DATETIME)
- add `registration_deadline` (DATETIME)
- add `created_by_id` (INTEGER)

If the project uses a non-sqlite database, the script will attempt a best-effort
ALTER TABLE via SQLAlchemy; for production systems prefer creating an Alembic
migration instead.
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
            # created_at
            if not column_exists(conn, 'tournament', 'created_at'):
                print('Adding column `created_at`')
                conn.execute("ALTER TABLE tournament ADD COLUMN created_at DATETIME")
                conn.commit()
                print('`created_at` added')
            else:
                print('`created_at` already exists')

            # registration_deadline
            if not column_exists(conn, 'tournament', 'registration_deadline'):
                print('Adding column `registration_deadline`')
                conn.execute("ALTER TABLE tournament ADD COLUMN registration_deadline DATETIME")
                conn.commit()
                print('`registration_deadline` added')
            else:
                print('`registration_deadline` already exists')

            # created_by_id
            if not column_exists(conn, 'tournament', 'created_by_id'):
                print('Adding column `created_by_id`')
                conn.execute("ALTER TABLE tournament ADD COLUMN created_by_id INTEGER")
                conn.commit()
                print('`created_by_id` added')
            else:
                print('`created_by_id` already exists')

        finally:
            conn.close()
    else:
        # Best-effort for other DB backends: try ALTER TABLE via SQLAlchemy
        with engine.connect() as conn:
            # Note: many RDBMS require ALTER TABLE ADD COLUMN with proper SQL
            try:
                conn.execute('ALTER TABLE tournament ADD COLUMN created_at DATETIME')
            except Exception as e:
                print('Could not add created_at automatically:', e)
            try:
                conn.execute('ALTER TABLE tournament ADD COLUMN registration_deadline DATETIME')
            except Exception as e:
                print('Could not add registration_deadline automatically:', e)
            try:
                conn.execute('ALTER TABLE tournament ADD COLUMN created_by_id INTEGER')
            except Exception as e:
                print('Could not add created_by_id automatically:', e)

print('Done')
