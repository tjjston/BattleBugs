import sys
from app import create_app, db
from app.models import Bug

"""
Rescale legacy bug stats from ~1-10 to 0-100.
- Multiplies attack/defense/speed/special_attack/special_defense by 10 if values look <= 10.
- Caps values at 100.
Run:
  python .\scripts\rescale_bug_stats.py
"""

def main():
    app = create_app()
    with app.app_context():
        updated = 0
        bugs = Bug.query.all()
        for b in bugs:
            changed = False
            for attr in ['attack', 'defense', 'speed', 'special_attack', 'special_defense']:
                val = getattr(b, attr, None)
                if val is None:
                    continue
                # Heuristic: if any core stat <= 10 and not obviously already scaled, scale by 10
                if val <= 10:
                    new_val = max(0, min(100, int(val * 10)))
                    if new_val != val:
                        setattr(b, attr, new_val)
                        changed = True
            if changed:
                updated += 1
        db.session.commit()
        print(f"Rescaled stats for {updated} bugs.")

if __name__ == '__main__':
    sys.exit(main())
