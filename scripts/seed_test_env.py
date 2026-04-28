#!/usr/bin/env python3
"""Seed a comprehensive test environment for BattleBugs.

Creates test users, species, bugs (various conditions), battles, a tournament,
classification flags, and notifications — all without calling any LLM.

Usage:
    python scripts/seed_test_env.py
    python scripts/seed_test_env.py --reset   # drop and recreate all test data

All test accounts use password: TestPass123!
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
import imagehash as _imagehash

from app import create_app, db
from app.models import (
    Battle, BlockedImageHash, Bug, BugAchievement, BugLore, BugRival,
    ClassificationFlag, Comment, Notification, Species, SystemSetting,
    Tournament, TournamentApplication, User,
)
from app.services.achievements import award_battle_achievements, award_submission_achievements

TEST_PASSWORD = "TestPass123!"
UPLOAD_DIR = ROOT / "app" / "static" / "uploads"

# ── Image helpers ──────────────────────────────────────────────────────────────

def _checkerboard(path: Path, color_a, color_b, size=400, tile=40):
    img = Image.new("RGB", (size, size), color_a)
    for row in range(0, size, tile):
        for col in range(0, size, tile):
            if (row // tile + col // tile) % 2:
                for y in range(row, min(row + tile, size)):
                    for x in range(col, min(col + tile, size)):
                        img.putpixel((x, y), color_b)
    img.save(path)
    return str(_imagehash.average_hash(img))


def make_test_images():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    specs = {
        "test_cricket.png":       ((34, 139, 34),  (0, 80, 0)),
        "test_ladybug.png":       ((200, 30, 30),  (10, 10, 10)),
        "test_spider.png":        ((80, 40, 20),   (40, 20, 10)),
        "test_beetle.png":        ((0, 50, 150),   (0, 20, 80)),
        "test_zombug.png":        ((100, 200, 100),(50, 100, 50)),
        "test_squashed.png":      ((150, 100, 50), (80, 50, 20)),
        "test_damaged_wings.png": ((200, 180, 50), (100, 90, 25)),
        "test_damaged_legs.png":  ((180, 100, 200),(90, 50, 100)),
        "test_scarred.png":       ((120, 120, 120),(60, 60, 60)),
        "test_flag_target.png":   ((255, 128, 0),  (128, 64, 0)),
    }
    hashes = {}
    for fname, (ca, cb) in specs.items():
        p = UPLOAD_DIR / fname
        hashes[fname] = _checkerboard(p, ca, cb)
    return hashes


# ── User helpers ───────────────────────────────────────────────────────────────

def _get_or_create_user(username, email, role="USER", **kwargs):
    u = User.query.filter_by(username=username).first()
    if u:
        return u, False
    u = User(username=username, email=email, role=role, **kwargs)
    u.set_password(TEST_PASSWORD)
    db.session.add(u)
    db.session.flush()
    return u, True


# ── Schema patcher ────────────────────────────────────────────────────────────

def _apply_schema_patches():
    """Add any missing columns to existing tables (idempotent, SQLite-safe)."""
    from sqlalchemy import text

    def _columns(table):
        rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}

    def _add_if_missing(table, column, typedef):
        if column not in _columns(table):
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}"))
            print(f"  + {table}.{column}")

    # User — guess tracking
    _add_if_missing("user", "total_guesses",   "INTEGER DEFAULT 0")
    _add_if_missing("user", "correct_guesses", "INTEGER DEFAULT 0")
    _add_if_missing("user", "skipped_guesses", "INTEGER DEFAULT 0")

    # Bug — condition fields + lethality/grip/cunning + is_zombug
    _add_if_missing("bug", "lethality",       "INTEGER DEFAULT 50")
    _add_if_missing("bug", "grip",            "INTEGER DEFAULT 50")
    _add_if_missing("bug", "cunning",         "INTEGER DEFAULT 50")
    _add_if_missing("bug", "is_zombug",       "BOOLEAN DEFAULT 0")
    _add_if_missing("bug", "condition",       "VARCHAR(30) DEFAULT 'alive'")
    _add_if_missing("bug", "condition_notes", "TEXT")
    _add_if_missing("bug", "is_retired",      "BOOLEAN DEFAULT 0")
    _add_if_missing("bug", "retired_at",      "DATETIME")
    _add_if_missing("bug", "stat_growth",     "INTEGER DEFAULT 0")
    _add_if_missing("bug", "image_hash",      "VARCHAR(64)")

    # BugRival — per-side win counts
    _add_if_missing("bug_rival", "bug1_wins", "INTEGER DEFAULT 0")
    _add_if_missing("bug_rival", "bug2_wins", "INTEGER DEFAULT 0")

    # Tournament — season key + format
    _add_if_missing("tournament", "season_key", "VARCHAR(20)")
    _add_if_missing("tournament", "format", "VARCHAR(30) DEFAULT 'single_elimination'")
    _add_if_missing("tournament", "submissions_per_user", "INTEGER DEFAULT 2")

    # SystemSetting — create table if not present (simple CREATE IF NOT EXISTS)
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS system_setting (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME,
            updated_by_id INTEGER REFERENCES user(id)
        )
    """))

    db.session.commit()
    print("Schema patches applied.")


# ── Main seeder ────────────────────────────────────────────────────────────────

def seed(reset=False):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating test images...")
    hashes = make_test_images()

    if reset:
        print("Resetting test data...")
        # Remove test users and cascade
        for uname in ["testowner", "testuser1", "testuser2", "testuser3", "testmod", "testadmin"]:
            u = User.query.filter_by(username=uname).first()
            if u:
                for bug in u.bugs.all():
                    ClassificationFlag.query.filter_by(bug_id=bug.id).delete()
                    BugAchievement.query.filter_by(bug_id=bug.id).delete()
                    BugLore.query.filter_by(bug_id=bug.id).delete()
                    Comment.query.filter_by(bug_id=bug.id).delete()
                    BugRival.query.filter(
                        (BugRival.bug1_id == bug.id) | (BugRival.bug2_id == bug.id)
                    ).delete()
                    Battle.query.filter(
                        (Battle.bug1_id == bug.id) | (Battle.bug2_id == bug.id)
                    ).delete()
                db.session.delete(u)
        db.session.commit()

    # ── Users ──────────────────────────────────────────────────────────────────
    print("Creating test users...")

    testowner, _ = _get_or_create_user(
        "testowner", "testowner@test.local", role="OWNER",
        accolade_points=9999, elo=1800, tournaments_won=3, bugs_submitted=0,
    )
    testadmin, _ = _get_or_create_user(
        "testadmin", "testadmin@test.local", role="ADMIN",
        accolade_points=1000, elo=1500,
    )
    testmod, _ = _get_or_create_user(
        "testmod", "testmod@test.local", role="MODERATOR",
        accolade_points=300, elo=1200,
    )
    # Good guesser — earned "Expert Entomologist"
    testuser1, _ = _get_or_create_user(
        "testuser1", "testuser1@test.local",
        accolade_points=150, elo=1100,
        total_guesses=10, correct_guesses=8, skipped_guesses=2,
    )
    # Terrible guesser — will earn "Spectacularly Wrong"
    testuser2, _ = _get_or_create_user(
        "testuser2", "testuser2@test.local",
        accolade_points=50, elo=950,
        total_guesses=7, correct_guesses=0, skipped_guesses=1,
    )
    # Never guesses — earns "Above It All"
    testuser3, _ = _get_or_create_user(
        "testuser3", "testuser3@test.local",
        accolade_points=80, elo=1000,
        total_guesses=0, correct_guesses=0, skipped_guesses=8,
    )
    db.session.commit()
    print(f"  Users: {testadmin.username}, {testmod.username}, {testuser1.username}, {testuser2.username}, {testuser3.username}")

    # ── Species ────────────────────────────────────────────────────────────────
    print("Creating test species...")

    def _get_or_create_species(scientific_name, **kwargs):
        s = Species.query.filter_by(scientific_name=scientific_name).first()
        if not s:
            s = Species(scientific_name=scientific_name, data_source="test_seed", **kwargs)
            db.session.add(s)
            db.session.flush()
        return s

    sp_cricket  = _get_or_create_species("Gryllus pennsylvanicus", common_name="Field Cricket",
                                         order="Orthoptera", family="Gryllidae")
    sp_ladybug  = _get_or_create_species("Coccinella septempunctata", common_name="Seven-spot Ladybug",
                                         order="Coleoptera", family="Coccinellidae")
    sp_spider   = _get_or_create_species("Latrodectus variolus", common_name="Northern Black Widow",
                                         order="Araneae", family="Theridiidae")
    sp_beetle   = _get_or_create_species("Dynastes tityus", common_name="Eastern Hercules Beetle",
                                         order="Coleoptera", family="Scarabaeidae")
    sp_fly      = _get_or_create_species("Exorista mella", common_name="Tachinid Fly",
                                         order="Diptera", family="Tachinidae")
    db.session.commit()

    # ── Bug factory ─────────────────────────────────────────────────────────────
    print("Creating test bugs...")

    def _make_bug(owner, nickname, image_file, species, atk, dfn, spd, lth=50, grp=50, cng=50,
                  attack_type="piercing", defense_type="hard_shell", size_class="small",
                  condition="alive", is_zombug=False, condition_notes=None,
                  wins=0, losses=0, tier="uu", **kwargs):
        existing = Bug.query.filter_by(nickname=nickname, user_id=owner.id).first()
        if existing:
            return existing
        h = hashes.get(image_file, "0000000000000000")
        bug = Bug(
            nickname=nickname, image_path=image_file, user_id=owner.id,
            common_name=species.common_name, scientific_name=species.scientific_name,
            species_id=species.id,
            attack=atk, defense=dfn, speed=spd,
            lethality=lth, grip=grp, cunning=cng,
            attack_type=attack_type, defense_type=defense_type, size_class=size_class,
            xfactor=random.uniform(-2, 2),
            stats_generated=True, stats_generation_method="test_seed",
            vision_verified=True, vision_confidence=0.92,
            vision_identified_species=species.scientific_name,
            tier=tier, wins=wins, losses=losses,
            condition=condition, is_zombug=is_zombug, condition_notes=condition_notes,
            image_hash=h,
            **kwargs,
        )
        if condition != "alive" and not is_zombug:
            bug.flair = {
                "squashed":      "💀 Battle-Worn",
                "damaged_wings": "🩹 Grounded",
                "damaged_legs":  "🦿 Limping",
                "damaged":       "⚔️ Scarred",
            }.get(condition)
        if is_zombug:
            bug.flair = "🧟 Zombug"
        db.session.add(bug)
        db.session.flush()
        award_submission_achievements(bug)
        return bug

    # Healthy bugs
    cricket1 = _make_bug(testuser1, "Jiminy Crusher", "test_cricket.png", sp_cricket,
                         atk=62, dfn=45, spd=78, lth=40, grp=55, cng=70,
                         attack_type="slashing", defense_type="evasive", size_class="small",
                         wins=5, losses=2, tier="uu")
    ladybug1 = _make_bug(testuser2, "Dot Destroyer", "test_ladybug.png", sp_ladybug,
                         atk=50, dfn=68, spd=55, lth=45, grp=60, cng=48,
                         attack_type="chemical", defense_type="hard_shell", size_class="tiny",
                         wins=3, losses=3, tier="uu")
    spider1 = _make_bug(testmod, "Black Vengeance", "test_spider.png", sp_spider,
                        atk=88, dfn=62, spd=84, lth=92, grp=70, cng=75,
                        attack_type="venom", defense_type="evasive", size_class="small",
                        wins=12, losses=1, tier="ou",
                        lore_background="Once survived a shoe attack by pure spite.")
    beetle1 = _make_bug(testadmin, "Hercules Jr", "test_beetle.png", sp_beetle,
                        atk=92, dfn=88, spd=42, lth=55, grp=85, cng=38,
                        attack_type="crushing", defense_type="hard_shell", size_class="large",
                        wins=8, losses=4, tier="ou")

    # Zombug — successful conversion
    zombug = _make_bug(testuser3, "The Undying", "test_zombug.png", sp_fly,
                       atk=66, dfn=66, spd=51, lth=69, grp=48, cng=42,
                       attack_type="venom", defense_type="toxic_skin", size_class="small",
                       condition="dead", is_zombug=True,
                       condition_notes="Specimen arrived motionless and stiff. The zombugification ritual succeeded on the second attempt.",
                       wins=2, losses=5, tier="uu")

    # Squashed bug
    squashed = _make_bug(testuser1, "Flat Stanley", "test_squashed.png", sp_ladybug,
                         atk=33, dfn=27, spd=30, lth=36, grp=36, cng=43,
                         attack_type="chemical", defense_type="hard_shell", size_class="tiny",
                         condition="squashed",
                         condition_notes="The specimen is visibly flattened, likely from a footfall. Body integrity is compromised but it's technically still mobile.",
                         wins=0, losses=4, tier="ru")

    # Damaged wings
    grounded = _make_bug(testuser2, "Broken Wings", "test_damaged_wings.png", sp_cricket,
                         atk=58, dfn=42, spd=44, lth=38, grp=52, cng=54,
                         attack_type="slashing", defense_type="evasive", size_class="small",
                         condition="damaged_wings",
                         condition_notes="Both hindwings are torn and the forewings show significant fraying. Cannot achieve flight.",
                         wins=1, losses=3, tier="uu")

    # Damaged legs
    limper = _make_bug(testuser3, "Three-Legger", "test_damaged_legs.png", sp_spider,
                       atk=80, dfn=58, spd=51, lth=85, grp=45, cng=68,
                       attack_type="venom", defense_type="evasive", size_class="small",
                       condition="damaged_legs",
                       condition_notes="Two legs are missing from the left side, likely from a previous encounter. Gait is noticeably uneven.",
                       wins=3, losses=6, tier="uu")

    # Bug with a pending classification flag (will be flagged below)
    flag_target = _make_bug(testuser2, "Mystery Bug", "test_flag_target.png", sp_cricket,
                            atk=45, dfn=40, spd=60, lth=45, grp=50, cng=55,
                            wins=1, losses=1, tier="uu")

    db.session.commit()
    all_bugs = [cricket1, ladybug1, spider1, beetle1, zombug, squashed, grounded, limper, flag_target]
    print(f"  Bugs: {[b.nickname for b in all_bugs]}")

    # ── Battles ────────────────────────────────────────────────────────────────
    print("Creating test battles...")

    def _make_battle(b1, b2, winner, days_ago=0):
        existing = Battle.query.filter(
            ((Battle.bug1_id == b1.id) & (Battle.bug2_id == b2.id)) |
            ((Battle.bug1_id == b2.id) & (Battle.bug2_id == b1.id))
        ).first()
        if existing:
            return existing
        battle = Battle(
            bug1_id=b1.id, bug2_id=b2.id,
            winner_id=winner.id if winner else None,
            battle_date=datetime.utcnow() - timedelta(days=days_ago),
            narrative=f"{b1.nickname} clashed with {b2.nickname}. {'Neither surrendered.' if not winner else f'{winner.nickname} emerged victorious.'}",
        )
        db.session.add(battle)
        db.session.flush()
        if winner:
            loser = b2 if winner.id == b1.id else b1
            award_battle_achievements(winner, loser=loser)
        return battle

    _make_battle(cricket1, ladybug1, cricket1, days_ago=10)
    _make_battle(spider1, beetle1,   spider1,  days_ago=8)
    _make_battle(zombug,  grounded,  grounded, days_ago=6)
    _make_battle(cricket1, spider1,  spider1,  days_ago=5)
    _make_battle(beetle1,  ladybug1, beetle1,  days_ago=3)
    _make_battle(limper,   squashed, limper,   days_ago=2)
    _make_battle(zombug,   cricket1, cricket1, days_ago=1)
    db.session.commit()

    # ── Rivals ─────────────────────────────────────────────────────────────────
    print("Creating rival pair...")
    b1_id, b2_id = sorted([cricket1.id, spider1.id])
    existing_rival = BugRival.query.filter_by(bug1_id=b1_id, bug2_id=b2_id).first()
    if not existing_rival:
        rival = BugRival(
            bug1_id=b1_id, bug2_id=b2_id,
            encounter_count=3,
            bug1_wins=1 if b1_id == cricket1.id else 2,
            bug2_wins=2 if b1_id == cricket1.id else 1,
        )
        db.session.add(rival)
        db.session.commit()

    # ── Lore entries ───────────────────────────────────────────────────────────
    print("Adding lore...")
    if not BugLore.query.filter_by(bug_id=spider1.id).first():
        lore = BugLore(
            bug_id=spider1.id, user_id=testuser1.id,
            lore_text="They say Black Vengeance once paralyzed a fly just by staring at it.",
            upvotes=4,
        )
        db.session.add(lore)
    if not BugLore.query.filter_by(bug_id=zombug.id).first():
        lore2 = BugLore(
            bug_id=zombug.id, user_id=testmod.id,
            lore_text="The Undying refuses to accept death as a valid excuse to stop fighting.",
            upvotes=7,
        )
        db.session.add(lore2)
    db.session.commit()

    # ── Comments ───────────────────────────────────────────────────────────────
    if not Comment.query.filter_by(bug_id=squashed.id).first():
        db.session.add(Comment(
            bug_id=squashed.id, user_id=testuser1.id,
            text="I can't believe this bug still showed up. Respect.",
        ))
    if not Comment.query.filter_by(bug_id=zombug.id).first():
        db.session.add(Comment(
            bug_id=zombug.id, user_id=testuser2.id,
            text="Is... is it supposed to smell like that?",
        ))
    db.session.commit()

    # ── Classification flag ────────────────────────────────────────────────────
    print("Creating classification flag...")
    if not ClassificationFlag.query.filter_by(bug_id=flag_target.id, flagging_user_id=testuser1.id).first():
        flag = ClassificationFlag(
            bug_id=flag_target.id,
            flagging_user_id=testuser1.id,
            reason="This doesn't look like a cricket to me — the body shape is more consistent with a katydid (Tettigoniidae). "
                   "The leg proportions and wing structure don't match Gryllidae.",
            suggested_species="Eastern Katydid (Scudderia furcata)",
            status="pending",
        )
        db.session.add(flag)
        db.session.commit()

    # ── Notifications ──────────────────────────────────────────────────────────
    print("Creating sample notification...")
    if not Notification.query.filter_by(user_id=testuser1.id).first():
        db.session.add(Notification(
            user_id=testuser1.id,
            message=f'Your classification dispute for "{flag_target.nickname}" has been received and is under review.',
            link_url=f'/bug/{flag_target.id}',
            is_read=False,
        ))
        db.session.commit()

    # ── Tournament ─────────────────────────────────────────────────────────────
    print("Creating test tournament...")
    if not Tournament.query.filter_by(name="Test Arena Cup").first():
        now = datetime.utcnow()
        tourney = Tournament(
            name="Test Arena Cup",
            start_date=now + timedelta(days=14),
            registration_deadline=now + timedelta(days=7),
            status="registration",
            max_participants=8,
        )
        db.session.add(tourney)
        db.session.flush()

        # Enroll a few bugs
        for bug in [cricket1, spider1, beetle1, zombug]:
            if not TournamentApplication.query.filter_by(tournament_id=tourney.id, bug_id=bug.id).first():
                app_ = TournamentApplication(
                    tournament_id=tourney.id,
                    bug_id=bug.id,
                    user_id=bug.user_id,
                    status="approved",
                )
                db.session.add(app_)
        db.session.commit()

    # ── Blocked hash demo ──────────────────────────────────────────────────────
    print("Adding a sample blocked hash...")
    demo_hash = "deadbeefdeadbeef"
    if not BlockedImageHash.query.filter_by(image_hash=demo_hash).first():
        db.session.add(BlockedImageHash(image_hash=demo_hash, reason="zombug_failed"))
        db.session.commit()

    print("\n✅ Test environment seeded successfully!")
    print("─" * 50)
    print(f"Password for all test accounts: {TEST_PASSWORD}")
    print("Accounts:")
    print("  testadmin  — ADMIN")
    print("  testmod    — MODERATOR")
    print("  testuser1  — Expert Entomologist (good guesser)")
    print("  testuser2  — Spectacularly Wrong (terrible guesser)")
    print("  testuser3  — Above It All (never guesses)")
    print("\nNotable bugs:")
    print(f"  {zombug.nickname} (id={zombug.id})    — 🧟 Zombug")
    print(f"  {squashed.nickname} (id={squashed.id}) — 💀 Battle-Worn (squashed)")
    print(f"  {grounded.nickname} (id={grounded.id}) — 🩹 Grounded (damaged wings)")
    print(f"  {limper.nickname} (id={limper.id})   — 🦿 Limping (damaged legs)")
    print(f"  {flag_target.nickname} (id={flag_target.id}) — pending classification dispute")
    print(f"\nTest images written to: {UPLOAD_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete existing test data before seeding")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        # Ensure schema is up to date without relying on Alembic chain
        _apply_schema_patches()
        db.create_all()  # creates any brand-new tables defined in the models
        seed(reset=args.reset)
