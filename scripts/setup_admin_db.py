"""Setup DB for admin use: backup, run migrations (or fallback scripts), verify columns, optionally promote a user.

Usage (PowerShell or cmd):
  .\.venv\Scripts\python.exe .\scripts\setup_admin_db.py --promote your-username

This script will:
 - Backup `database/bug_arena.db` to `database/bug_arena.db.bak`
 - Try `python -m flask db upgrade` (using the same Python interpreter)
 - If that fails, run helper scripts in `scripts/` to add missing columns
 - Verify the `user` table has the `role` column
 - Optionally promote a user to OWNER (or other role)

Designed to be safe for local/dev use. Review output before running in production.
"""
import argparse
import os
import shutil
import subprocess
import sys
import sqlite3

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_PATH = os.path.join(REPO_ROOT, 'database', 'bug_arena.db')
BACKUP_PATH = DB_PATH + '.bak'


def backup_db():
    if not os.path.exists(DB_PATH):
        print('DB file not found at', DB_PATH)
        return False
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print('Backup created at', BACKUP_PATH)
    return True


def try_alembic_upgrade():
    print('Attempting Alembic upgrade via flask CLI...')
    # Use the same Python interpreter that runs this script
    cmd = [sys.executable, '-m', 'flask', 'db', 'upgrade']
    try:
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
        print(res.stdout)
        if res.returncode == 0:
            print('Alembic upgrade completed successfully.')
            return True
        else:
            print('Alembic upgrade failed (return code', res.returncode, ').')
            print('stderr:', res.stderr)
            return False
    except FileNotFoundError:
        print('Flask CLI not found in this environment.')
        return False


def run_helper_scripts():
    print('Running fallback helper scripts...')
    helpers = ['add_tournament_fields.py', 'add_user_fields.py', 'add_max_participants.py']
    for script in helpers:
        path = os.path.join(REPO_ROOT, 'scripts', script)
        if os.path.exists(path):
            print('Running', script)
            res = subprocess.run([sys.executable, path], cwd=REPO_ROOT)
            if res.returncode != 0:
                print(script, 'exited with code', res.returncode)
        else:
            print('Helper script not found:', script)


def user_table_has_column(column_name: str) -> bool:
    if not os.path.exists(DB_PATH):
        print('DB not found at', DB_PATH)
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("PRAGMA table_info('user')")
        cols = [r[1] for r in cur.fetchall()]
        print('user table columns:', cols)
        return column_name in cols
    finally:
        conn.close()


def promote_user(username: str, role: str = 'OWNER', elo: int = 1500):
    path = os.path.join(REPO_ROOT, 'scripts', 'promote_user.py')
    if not os.path.exists(path):
        print('promote_user.py not found; cannot promote')
        return False
    cmd = [sys.executable, path, '--username', username, '--role', role, '--elo', str(elo)]
    res = subprocess.run(cmd, cwd=REPO_ROOT)
    return res.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--promote', help='Username to promote after migration completes')
    parser.add_argument('--no-backup', action='store_true', help='Skip DB backup')
    parser.add_argument('--no-fallback', action='store_true', help='Do not run fallback helper scripts')
    args = parser.parse_args()

    if not args.no_backup:
        ok = backup_db()
        if not ok:
            print('Aborting: DB backup failed or DB missing.')
            return 1

    upgraded = try_alembic_upgrade()
    if not upgraded and not args.no_fallback:
        run_helper_scripts()

    # Verify role column exists
    if user_table_has_column('role'):
        print('role column present in user table.')
    else:
        print('role column still missing. You may need to run migrations manually or inspect logs.')

    if args.promote:
        if not user_table_has_column('role'):
            print('Cannot promote: role column missing.')
            return 1
        promoted = promote_user(args.promote)
        if promoted:
            print('Promotion succeeded')
        else:
            print('Promotion failed; check errors above')

    return 0


if __name__ == '__main__':
    sys.exit(main())
