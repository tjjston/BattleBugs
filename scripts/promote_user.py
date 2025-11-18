r"""Promote a user via the Flask app (ORM).

Usage:
    ./.venv/Scripts/python.exe scripts/promote_user.py --username yourname --role OWNER --elo 1500

This avoids shell quoting issues by using a small Python script.
"""
import os
import sys
import argparse

# Ensure repo root is on sys.path so 'app' package can be imported when running
# this script directly (e.g., from the `scripts/` folder).
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

from app import create_app, db
from config import Config
from app.models import User

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    parser.add_argument('--role', default='OWNER')
    parser.add_argument('--elo', type=int, default=1500)
    args = parser.parse_args()

    app = create_app(Config)
    with app.app_context():
        user = User.query.filter_by(username=args.username).first()
        if not user:
            print('User not found:', args.username)
            return

        user.role = args.role
        user.elo = args.elo
        db.session.commit()
        print('Updated user:', user.username, 'role=', user.role, 'elo=', user.elo)

if __name__ == '__main__':
    main()
