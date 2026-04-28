#!/usr/bin/env python3
"""Seed BattleBugs with local sample users, bugs, battles, and image manifests.

Default image inputs:
- Positive bug images: ./test bugs/*
- Negative submission references: ./test bugs/negative tests/*

The script is idempotent by username / bug nickname and does not call LLM services.
Run database migrations before using it against an existing database.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app, db
from app.models import (
    Battle,
    Bug,
    BugAchievement,
    BugLoreVote,
    BugLore,
    Comment,
    CommentVote,
    CurrencyTransaction,
    Job,
    Species,
    Tournament,
    TournamentApplication,
    TournamentMatch,
    User,
)
from app.services.achievements import award_battle_achievements, award_submission_achievements


DEFAULT_POSITIVE_DIR = ROOT / "test bugs"
DEFAULT_NEGATIVE_DIR = ROOT / "test bugs" / "negative tests"
DEFAULT_MANIFEST = ROOT / "sample_data" / "submission_image_manifest.json"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SAMPLE_PASSWORD = "battlebugs"


SAMPLE_USERS = [
    {
        "username": "testowner",
        "email": "testowner@example.com",
        "role": "OWNER",
        "elo": 1800,
        "accolade_points": 9999,
        "tournaments_won": 3,
    },
    {
        "username": "owner_ivy",
        "email": "owner_ivy@example.com",
        "role": "OWNER",
        "elo": 1400,
        "accolade_points": 500,
    },
    {
        "username": "mod_mason",
        "email": "mod_mason@example.com",
        "role": "MODERATOR",
        "elo": 1175,
        "accolade_points": 250,
    },
    {
        "username": "collector_nova",
        "email": "nova@example.com",
        "role": "USER",
        "elo": 1080,
        "accolade_points": 120,
    },
    {
        "username": "field_scout_rin",
        "email": "rin@example.com",
        "role": "USER",
        "elo": 1040,
        "accolade_points": 95,
    },
    {
        "username": "arena_jo",
        "email": "jo@example.com",
        "role": "USER",
        "elo": 1000,
        "accolade_points": 80,
    },
]


SAMPLE_BUGS = [
    {
        "image_index": 0,
        "owner": "collector_nova",
        "nickname": "Ironclad Thorn",
        "common_name": "Armored Beetle",
        "scientific_name": "Coleoptera specimen",
        "order": "Coleoptera",
        "family": "Scarabaeidae",
        "description": "Found patrolling a cracked garden stone after rain.",
        "location_found": "Backyard stone path",
        "attack": 68,
        "defense": 86,
        "speed": 34,
        "attack_type": "crushing",
        "defense_type": "hard_shell",
        "size_class": "medium",
        "special_ability": "Shellbreaker Charge",
        "tier": "ou",
        "wins": 3,
        "losses": 1,
        "lore_background": "Raised under a mossy slab where every pebble became a fortress wall.",
        "lore_motivation": "Fights to prove armor and patience can outlast spectacle.",
        "lore_personality": "Methodical, stubborn, and impossible to intimidate.",
    },
    {
        "image_index": 1,
        "owner": "field_scout_rin",
        "nickname": "Verdant Hook",
        "common_name": "Mantis",
        "scientific_name": "Mantodea specimen",
        "order": "Mantodea",
        "family": "Mantidae",
        "description": "Spotted waiting motionless on a leaf with perfect ambush posture.",
        "location_found": "Vegetable garden",
        "attack": 82,
        "defense": 48,
        "speed": 73,
        "attack_type": "slashing",
        "defense_type": "evasive",
        "size_class": "medium",
        "special_ability": "Stillness Before Strike",
        "tier": "uber",
        "wins": 4,
        "losses": 2,
        "lore_background": "A silent duelist from the upper leaves, trained by wind and hunger.",
        "lore_motivation": "Fights to keep the canopy under its watch.",
        "lore_personality": "Patient, precise, and merciless once committed.",
    },
    {
        "image_index": 2,
        "owner": "arena_jo",
        "nickname": "Eight-Eye Static",
        "common_name": "Jumping Spider",
        "scientific_name": "Salticidae specimen",
        "order": "Araneae",
        "family": "Salticidae",
        "description": "Found watching from a window frame, tiny but completely unbothered.",
        "location_found": "Kitchen window ledge",
        "attack": 58,
        "defense": 42,
        "speed": 91,
        "attack_type": "venom",
        "defense_type": "evasive",
        "size_class": "tiny",
        "special_ability": "Angle Break Leap",
        "tier": "uu",
        "wins": 2,
        "losses": 3,
        "lore_background": "A wall-runner famous for impossible leaps and stranger patience.",
        "lore_motivation": "Fights to turn every arena into a vertical battlefield.",
        "lore_personality": "Curious, explosive, and always calculating the next angle.",
    },
    {
        "image_index": 3,
        "owner": "collector_nova",
        "nickname": "Amber Needle",
        "common_name": "Wasp",
        "scientific_name": "Hymenoptera specimen",
        "order": "Hymenoptera",
        "family": "Vespidae",
        "description": "A tense winged challenger photographed near a fence rail.",
        "location_found": "Fence line",
        "attack": 76,
        "defense": 39,
        "speed": 84,
        "attack_type": "venom",
        "defense_type": "evasive",
        "size_class": "small",
        "special_ability": "Warning Stripe Feint",
        "tier": "ou",
        "wins": 5,
        "losses": 1,
        "lore_background": "Exiled from a paper citadel after refusing to bow.",
        "lore_motivation": "Fights for a new hive under its own command.",
        "lore_personality": "Sharp-tempered, regal, and brutally fast.",
    },
    {
        "image_index": 4,
        "owner": "field_scout_rin",
        "nickname": "Goliath Rootsplitter",
        "common_name": "Goliath Beetle",
        "scientific_name": "Goliathus specimen",
        "order": "Coleoptera",
        "family": "Scarabaeidae",
        "description": "A heavy arena favorite with enough mass to move the dirt beneath it.",
        "location_found": "Compost edge",
        "attack": 88,
        "defense": 78,
        "speed": 28,
        "attack_type": "crushing",
        "defense_type": "thick_hide",
        "size_class": "large",
        "special_ability": "Rootsplitter Slam",
        "tier": "uber",
        "wins": 6,
        "losses": 2,
        "lore_background": "A ground-shaking champion said to have trained under old roots.",
        "lore_motivation": "Fights because every arena needs a mountain to climb.",
        "lore_personality": "Heavy, proud, and almost impossible to rush.",
    },
    {
        "image_index": 5,
        "owner": "arena_jo",
        "nickname": "Dustwing Hex",
        "common_name": "Moth",
        "scientific_name": "Lepidoptera specimen",
        "order": "Lepidoptera",
        "family": "Noctuidae",
        "description": "A night fighter found beneath porch light glare.",
        "location_found": "Porch light",
        "attack": 44,
        "defense": 46,
        "speed": 66,
        "attack_type": "chemical",
        "defense_type": "hairy_spiny",
        "size_class": "small",
        "special_ability": "Powder Veil",
        "tier": "ru",
        "wins": 1,
        "losses": 4,
        "lore_background": "Born in lamp-glow and dust, with wings that remember every escape.",
        "lore_motivation": "Fights to prove fragile things can still haunt the bracket.",
        "lore_personality": "Skittish until cornered, then strange and difficult to read.",
    },
]


def image_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(
        p for p in path.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def get_or_create_user(spec: dict) -> User:
    user = User.query.filter_by(username=spec["username"]).first()
    if not user:
        user = User(username=spec["username"], email=spec["email"])
        user.set_password(SAMPLE_PASSWORD)
        db.session.add(user)
    user.email = spec["email"]
    user.role = spec["role"]
    user.elo = spec["elo"]
    user.accolade_points = spec["accolade_points"]
    if "tournaments_won" in spec:
        user.tournaments_won = spec["tournaments_won"]
    return user


def get_or_create_species(spec: dict) -> Species:
    species = Species.query.filter_by(scientific_name=spec["scientific_name"]).first()
    if not species:
        species = Species(scientific_name=spec["scientific_name"])
        db.session.add(species)
    species.common_name = spec["common_name"]
    species.order = spec["order"]
    species.family = spec["family"]
    species.data_source = "sample_seed"
    return species


def copy_sample_image(source: Path, upload_dir: Path, nickname: str) -> str:
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = nickname.lower().replace(" ", "_").replace("-", "_")
    target_name = f"sample_{safe_name}{source.suffix.lower()}"
    shutil.copy2(source, upload_dir / target_name)
    return target_name


def get_or_create_bug(spec: dict, users: dict[str, User], positives: list[Path], upload_dir: Path) -> Bug | None:
    if not positives:
        return None
    source = positives[spec["image_index"] % len(positives)]
    image_path = copy_sample_image(source, upload_dir, spec["nickname"])
    owner = users[spec["owner"]]
    species = get_or_create_species(spec)
    db.session.flush()

    bug = Bug.query.filter_by(nickname=spec["nickname"]).first()
    if not bug:
        bug = Bug(nickname=spec["nickname"], user_id=owner.id, image_path=image_path)
        db.session.add(bug)

    bug.user_id = owner.id
    bug.image_path = image_path
    bug.common_name = spec["common_name"]
    bug.scientific_name = spec["scientific_name"]
    bug.species_id = species.id
    bug.description = spec["description"]
    bug.location_found = spec["location_found"]
    bug.attack = spec["attack"]
    bug.defense = spec["defense"]
    bug.speed = spec["speed"]
    bug.attack_type = spec["attack_type"]
    bug.defense_type = spec["defense_type"]
    bug.size_class = spec["size_class"]
    bug.special_ability = spec["special_ability"]
    bug.tier = spec["tier"]
    bug.wins = spec["wins"]
    bug.losses = spec["losses"]
    bug.lore_background = spec["lore_background"]
    bug.lore_motivation = spec["lore_motivation"]
    bug.lore_personality = spec["lore_personality"]
    bug.stats_generated = True
    bug.stats_generation_method = "sample_seed"
    bug.vision_verified = True
    bug.vision_confidence = 0.96
    bug.is_verified = True
    bug.enrichment_status = "complete"
    bug.submission_date = datetime.utcnow() - timedelta(days=spec["image_index"] + 1)
    bug.generate_flair()
    already_rewarded = CurrencyTransaction.query.filter_by(
        reason="approved_bug_submission",
        reference_type="bug",
        reference_id=bug.id,
    ).first()
    if not already_rewarded:
        award_submission_achievements(bug)
    return bug


def add_social_data(bugs: list[Bug], users: dict[str, User]) -> None:
    comments = [
        (bugs[0], users["field_scout_rin"], "That shell is doing real bracket work."),
        (bugs[1], users["collector_nova"], "The posture alone deserves a seed."),
        (bugs[3], users["arena_jo"], "Fast, rude, and probably correct about it."),
    ]
    for bug, user, text in comments:
        if not Comment.query.filter_by(bug_id=bug.id, user_id=user.id, text=text).first():
            db.session.add(Comment(text=text, bug_id=bug.id, user_id=user.id, upvotes=1))

    lore_entries = [
        (bugs[0], users["arena_jo"], "Arena rumor says Ironclad Thorn sleeps inside a split acorn helmet."),
        (bugs[2], users["collector_nova"], "Eight-Eye Static once vanished mid-stare and reappeared on the judge's clipboard."),
        (bugs[4], users["mod_mason"], "Goliath Rootsplitter refuses to fight indoors after cracking a practice tile."),
    ]
    for bug, user, text in lore_entries:
        if not BugLore.query.filter_by(bug_id=bug.id, user_id=user.id, lore_text=text).first():
            db.session.add(BugLore(lore_text=text, bug_id=bug.id, user_id=user.id, upvotes=2))


def add_battles_and_tournament(bugs: list[Bug], owner: User) -> None:
    pairings = [
        (bugs[0], bugs[2], bugs[0], "Ironclad Thorn absorbed every leap before ending the bout with a grinding charge."),
        (bugs[1], bugs[5], bugs[1], "Verdant Hook waited through a cloud of dust, then cut the match short."),
        (bugs[3], bugs[4], bugs[3], "Amber Needle survived the opening crash and won by never standing still."),
    ]
    for bug1, bug2, winner, narrative in pairings:
        existing = Battle.query.filter_by(bug1_id=bug1.id, bug2_id=bug2.id, narrative=narrative).first()
        if not existing:
            db.session.add(Battle(
                bug1_id=bug1.id,
                bug2_id=bug2.id,
                winner_id=winner.id,
                narrative=narrative,
                battle_date=datetime.utcnow() - timedelta(days=len(narrative) % 7),
            ))
            award_battle_achievements(winner, bug2 if winner.id == bug1.id else bug1)

    tournament = Tournament.query.filter_by(name="Sample Spring Skirmish").first()
    if not tournament:
        tournament = Tournament(
            name="Sample Spring Skirmish",
            start_date=datetime.utcnow() + timedelta(days=5),
            status="registration",
            tier="ou",
            max_participants=8,
            created_by_id=owner.id,
            created_at=datetime.utcnow() - timedelta(days=3),
        )
        db.session.add(tournament)
        db.session.flush()

    for index, bug in enumerate(bugs[:4], start=1):
        app = TournamentApplication.query.filter_by(tournament_id=tournament.id, bug_id=bug.id).first()
        if not app:
            db.session.add(TournamentApplication(
                tournament_id=tournament.id,
                bug_id=bug.id,
                user_id=bug.user_id,
                status="approved",
                seed_number=index,
                reviewed_at=datetime.utcnow(),
                reviewed_by_id=owner.id,
            ))

    if not TournamentMatch.query.filter_by(tournament_id=tournament.id).first():
        db.session.add(TournamentMatch(
            tournament_id=tournament.id,
            round_number=1,
            match_number=1,
            bug1_id=bugs[0].id,
            bug2_id=bugs[1].id,
        ))
        db.session.add(TournamentMatch(
            tournament_id=tournament.id,
            round_number=1,
            match_number=2,
            bug1_id=bugs[2].id,
            bug2_id=bugs[3].id,
        ))


def write_manifest(positives: list[Path], negatives: list[Path], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "positive_bug_images": [
            {"path": str(path.relative_to(ROOT)), "expected": "approved_candidate"}
            for path in positives
        ],
        "negative_submission_images": [
            {"path": str(path.relative_to(ROOT)), "expected": "reject_submission"}
            for path in negatives
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def reset_sample_data() -> None:
    sample_usernames = [user["username"] for user in SAMPLE_USERS]
    sample_users = User.query.filter(User.username.in_(sample_usernames)).all()
    sample_user_ids = [user.id for user in sample_users]
    if sample_user_ids:
        sample_bug_ids = [bug.id for bug in Bug.query.filter(Bug.user_id.in_(sample_user_ids)).all()]
        if sample_bug_ids:
            comment_ids = [row[0] for row in db.session.query(Comment.id).filter(Comment.bug_id.in_(sample_bug_ids)).all()]
            lore_ids = [row[0] for row in db.session.query(BugLore.id).filter(BugLore.bug_id.in_(sample_bug_ids)).all()]
            if comment_ids:
                CommentVote.query.filter(CommentVote.comment_id.in_(comment_ids)).delete(synchronize_session=False)
            if lore_ids:
                BugLoreVote.query.filter(BugLoreVote.lore_id.in_(lore_ids)).delete(synchronize_session=False)
            Battle.query.filter(
                (Battle.bug1_id.in_(sample_bug_ids)) | (Battle.bug2_id.in_(sample_bug_ids))
            ).delete(synchronize_session=False)
            TournamentMatch.query.filter(
                (TournamentMatch.bug1_id.in_(sample_bug_ids)) | (TournamentMatch.bug2_id.in_(sample_bug_ids))
            ).delete(synchronize_session=False)
            TournamentApplication.query.filter(TournamentApplication.bug_id.in_(sample_bug_ids)).delete(synchronize_session=False)
            Comment.query.filter(Comment.bug_id.in_(sample_bug_ids)).delete(synchronize_session=False)
            BugLore.query.filter(BugLore.bug_id.in_(sample_bug_ids)).delete(synchronize_session=False)
            BugAchievement.query.filter(BugAchievement.bug_id.in_(sample_bug_ids)).delete(synchronize_session=False)
            for bug_id in sample_bug_ids:
                Job.query.filter(Job.payload_json.contains(f'"bug_id": {bug_id}')).delete(synchronize_session=False)
            CurrencyTransaction.query.filter(
                CurrencyTransaction.reference_type == "bug",
                CurrencyTransaction.reference_id.in_(sample_bug_ids),
            ).delete(synchronize_session=False)
            Bug.query.filter(Bug.id.in_(sample_bug_ids)).delete(synchronize_session=False)
        CurrencyTransaction.query.filter(CurrencyTransaction.user_id.in_(sample_user_ids)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(sample_user_ids)).delete(synchronize_session=False)
    tournament = Tournament.query.filter_by(name="Sample Spring Skirmish").first()
    if tournament:
        TournamentMatch.query.filter_by(tournament_id=tournament.id).delete()
        TournamentApplication.query.filter_by(tournament_id=tournament.id).delete()
        db.session.delete(tournament)
    db.session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local BattleBugs sample data.")
    parser.add_argument("--positive-dir", default=str(DEFAULT_POSITIVE_DIR), help="Directory containing valid bug images.")
    parser.add_argument("--negative-dir", default=str(DEFAULT_NEGATIVE_DIR), help="Directory containing images that should fail submission.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Where to write image manifest JSON.")
    parser.add_argument("--reset-sample", action="store_true", help="Remove existing sample users/bugs before seeding.")
    parser.add_argument("--create-schema", action="store_true", help="Create missing tables first. Use migrations for normal app databases.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.create_schema:
            db.create_all()

        if args.reset_sample:
            reset_sample_data()

        positives = image_files(Path(args.positive_dir))
        negatives = image_files(Path(args.negative_dir))
        if not positives:
            raise SystemExit(f"No positive bug images found in {args.positive_dir}")

        users = {spec["username"]: get_or_create_user(spec) for spec in SAMPLE_USERS}
        db.session.commit()

        bugs = [
            bug for bug in (
                get_or_create_bug(spec, users, positives, Path(app.config["UPLOAD_FOLDER"]))
                for spec in SAMPLE_BUGS
            )
            if bug is not None
        ]
        db.session.commit()

        add_social_data(bugs, users)
        add_battles_and_tournament(bugs, users["owner_ivy"])
        db.session.commit()

        write_manifest(positives, negatives, Path(args.manifest))

        print("Seeded sample users:")
        for spec in SAMPLE_USERS:
            print(f"  {spec['username']} / {SAMPLE_PASSWORD} ({spec['role']})")
        print(f"Seeded {len(bugs)} bugs from {args.positive_dir}")
        print(f"Recorded {len(negatives)} negative submission references")
        print(f"Manifest: {args.manifest}")


if __name__ == "__main__":
    main()
