Database Migrations & One-off Helpers
===================================

This document explains how to apply Alembic migrations and use the helper scripts in `scripts/` if Alembic can't be run.

Recommended (safe) path — Alembic

1. Backup your DB

PowerShell:

```
Copy-Item -Path .\\database\\bug_arena.db -Destination .\\database\\bug_arena.db.bak -Force
```

cmd:

```
copy /Y database\\bug_arena.db database\\bug_arena.db.bak
```

2. Activate venv (optional) and run Alembic upgrade

PowerShell:

```
.\\.venv\\Scripts\\Activate.ps1
# if your environment requires FLASK_APP to be set, set it in the same shell before running the next commands
python -m flask db upgrade
```

cmd:

```
.\\.venv\\Scripts\\activate.bat
:: set FLASK_APP=run.py   (if required)
python -m flask db upgrade
```

Alternate: run the helper scripts (dev only)

If Alembic cannot be used, run the helper scripts that add missing columns directly to the sqlite DB. These are intended for local/dev use only.

PowerShell / cmd (both):

```
.\\.venv\\Scripts\\python.exe .\\scripts\\add_tournament_fields.py
.\\.venv\\Scripts\\python.exe .\\scripts\\add_user_fields.py
.\\.venv\\Scripts\\python.exe .\\scripts\\add_max_participants.py
```

Verification

Check table columns:

PowerShell / cmd (sqlite3):

```
sqlite3 .\\database\\bug_arena.db "PRAGMA table_info('user');"
```

Or use Python:

```
.\\.venv\\Scripts\\python.exe - <<'PY'
import sqlite3
conn = sqlite3.connect('database/bug_arena.db')
print([r[1] for r in conn.execute("PRAGMA table_info('user')").fetchall()])
conn.close()
PY
```

If you run into problems, capture the exact traceback and share it.
