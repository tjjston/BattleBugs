"""Check columns on the `user` table in the project's SQLite DB.

Usage:
  .\.venv\Scripts\python.exe scripts\check_user_columns.py

This script prints the list of column names for the `user` table.
"""
import sqlite3
import os
from config import Config

def get_db_path():
    uri = Config.SQLALCHEMY_DATABASE_URI
    if uri.startswith('sqlite'):
        return uri.split('///', 1)[-1]
    return None

def main():
    db_path = get_db_path()
    if not db_path or not os.path.exists(db_path):
        print('SQLite DB not found at', db_path)
        return

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("PRAGMA table_info('user')")
        cols = [row[1] for row in cur.fetchall()]
        print('Columns on user:', cols)
    finally:
        conn.close()

if __name__ == '__main__':
    main()
