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
    ContenderCallout,
    CurrencyTransaction,
    Job,
    Season,
    SeasonRegistration,
    Species,
    TierChampionship,
    TierRanking,
    TitleBid,
    TitleFight,
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
    # Staff accounts
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
    # Veteran players
    {
        "username": "collector_nova",
        "email": "nova@example.com",
        "role": "USER",
        "elo": 1080,
        "accolade_points": 320,
    },
    {
        "username": "field_scout_rin",
        "email": "rin@example.com",
        "role": "USER",
        "elo": 1040,
        "accolade_points": 195,
    },
    {
        "username": "arena_jo",
        "email": "jo@example.com",
        "role": "USER",
        "elo": 1000,
        "accolade_points": 140,
    },
    # Test accounts (easy logins for dev/QA)
    {
        "username": "testuser1",
        "email": "testuser1@example.com",
        "role": "USER",
        "elo": 960,
        "accolade_points": 75,
    },
    {
        "username": "testuser2",
        "email": "testuser2@example.com",
        "role": "USER",
        "elo": 940,
        "accolade_points": 60,
    },
    {
        "username": "testuser3",
        "email": "testuser3@example.com",
        "role": "USER",
        "elo": 920,
        "accolade_points": 45,
    },
    {
        "username": "testuser4",
        "email": "testuser4@example.com",
        "role": "USER",
        "elo": 905,
        "accolade_points": 30,
    },
    {
        "username": "backyard_benny",
        "email": "benny@example.com",
        "role": "USER",
        "elo": 890,
        "accolade_points": 20,
    },
]


# fmt: off
SAMPLE_BUGS = [
    # ── Tier: uber / ou ──────────────────────────────────────────────────────
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
        "attack": 68, "defense": 86, "speed": 34,
        "lethality": 55, "grip": 72, "cunning": 48,
        "attack_type": "crushing", "defense_type": "hard_shell",
        "size_class": "medium",
        "special_ability": "Shellbreaker Charge",
        "tier": "ou", "wins": 5, "losses": 2,
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
        "attack": 82, "defense": 48, "speed": 73,
        "lethality": 79, "grip": 61, "cunning": 67,
        "attack_type": "slashing", "defense_type": "evasive",
        "size_class": "medium",
        "special_ability": "Stillness Before Strike",
        "tier": "uber", "wins": 7, "losses": 2,
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
        "attack": 58, "defense": 42, "speed": 91,
        "lethality": 65, "grip": 74, "cunning": 80,
        "attack_type": "venom", "defense_type": "evasive",
        "size_class": "tiny",
        "special_ability": "Angle Break Leap",
        "tier": "uu", "wins": 4, "losses": 4,
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
        "attack": 76, "defense": 39, "speed": 84,
        "lethality": 82, "grip": 44, "cunning": 58,
        "attack_type": "venom", "defense_type": "evasive",
        "size_class": "small",
        "special_ability": "Warning Stripe Feint",
        "tier": "ou", "wins": 7, "losses": 2,
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
        "attack": 88, "defense": 78, "speed": 28,
        "lethality": 62, "grip": 85, "cunning": 38,
        "attack_type": "crushing", "defense_type": "thick_hide",
        "size_class": "large",
        "special_ability": "Rootsplitter Slam",
        "tier": "uber", "wins": 9, "losses": 3,
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
        "attack": 44, "defense": 46, "speed": 66,
        "lethality": 38, "grip": 33, "cunning": 55,
        "attack_type": "chemical", "defense_type": "hairy_spiny",
        "size_class": "small",
        "special_ability": "Powder Veil",
        "tier": "ru", "wins": 2, "losses": 5,
        "lore_background": "Born in lamp-glow and dust, with wings that remember every escape.",
        "lore_motivation": "Fights to prove fragile things can still haunt the bracket.",
        "lore_personality": "Skittish until cornered, then strange and difficult to read.",
    },

    # ── Common backyard bugs — the bread and butter of the arena ─────────────
    {
        "image_index": 0,
        "owner": "testuser1",
        "nickname": "Sir Stinks-a-Lot",
        "common_name": "Brown Marmorated Stink Bug",
        "scientific_name": "Halyomorpha halys",
        "order": "Hemiptera",
        "family": "Pentatomidae",
        "description": "Found sneaking through a window gap in autumn. Deployed its odor immediately.",
        "location_found": "Bedroom windowsill",
        "attack": 35, "defense": 55, "speed": 32,
        "lethality": 58, "grip": 40, "cunning": 44,
        "attack_type": "chemical", "defense_type": "hard_shell",
        "size_class": "small",
        "special_ability": "Stench Shield",
        "tier": "ru", "wins": 2, "losses": 3,
        "lore_background": "An autumn invader with an odor that clears the whole arena.",
        "lore_motivation": "Keeps fighting because everyone already hates it — nothing to lose.",
        "lore_personality": "Stubborn, patient, and chemically persuasive.",
    },
    {
        "image_index": 1,
        "owner": "testuser1",
        "nickname": "Lucky Seven",
        "common_name": "Seven-Spotted Ladybug",
        "scientific_name": "Coccinella septempunctata",
        "order": "Coleoptera",
        "family": "Coccinellidae",
        "description": "Spotted on a rose leaf. Deceptively armored.",
        "location_found": "Front garden roses",
        "attack": 28, "defense": 60, "speed": 55,
        "lethality": 52, "grip": 35, "cunning": 48,
        "attack_type": "chemical", "defense_type": "toxic_skin",
        "size_class": "tiny",
        "special_ability": "Reflex Bleed",
        "tier": "nu", "wins": 3, "losses": 2,
        "lore_background": "Underestimated since birth — predators learn quickly not to bite twice.",
        "lore_motivation": "Fights because small and toxic is better than big and boring.",
        "lore_personality": "Calm, bright, chemically loaded.",
    },
    {
        "image_index": 2,
        "owner": "testuser2",
        "nickname": "The Chirper",
        "common_name": "House Cricket",
        "scientific_name": "Acheta domesticus",
        "order": "Orthoptera",
        "family": "Gryllidae",
        "description": "Escaped from behind the water heater. Loud, relentless.",
        "location_found": "Basement utility room",
        "attack": 38, "defense": 30, "speed": 78,
        "lethality": 42, "grip": 28, "cunning": 65,
        "attack_type": "sonic", "defense_type": "evasive",
        "size_class": "small",
        "special_ability": "Resonance Chirp",
        "tier": "nu", "wins": 4, "losses": 3,
        "lore_background": "A natural survivor who weaponized the one thing no one could ignore: noise.",
        "lore_motivation": "Fights for the right to make sound in a world that keeps trying to silence it.",
        "lore_personality": "Relentlessly vocal, surprisingly strategic.",
    },
    {
        "image_index": 3,
        "owner": "testuser2",
        "nickname": "Ember Scout",
        "common_name": "Firefly",
        "scientific_name": "Photinus pyralis",
        "order": "Coleoptera",
        "family": "Lampyridae",
        "description": "Caught blinking in the tall grass at dusk.",
        "location_found": "Back meadow",
        "attack": 30, "defense": 45, "speed": 70,
        "lethality": 35, "grip": 32, "cunning": 72,
        "attack_type": "neutral", "defense_type": "bioluminescent",
        "size_class": "small",
        "special_ability": "Disorienting Flash",
        "tier": "nu", "wins": 2, "losses": 4,
        "lore_background": "A beacon in the dark — uses light as both weapon and shield.",
        "lore_motivation": "Fights to show the arena who truly owns the night.",
        "lore_personality": "Quiet, hypnotic, and full of tricks.",
    },
    {
        "image_index": 4,
        "owner": "testuser3",
        "nickname": "Rollie McRoll",
        "common_name": "Pillbug",
        "scientific_name": "Armadillidium vulgare",
        "order": "Isopoda",
        "family": "Armadillidiidae",
        "description": "Found curled up under a garden pot lid. Refuses to unroll for photographs.",
        "location_found": "Under flower pot",
        "attack": 18, "defense": 78, "speed": 18,
        "lethality": 22, "grip": 30, "cunning": 35,
        "attack_type": "neutral", "defense_type": "segmented_armor",
        "size_class": "tiny",
        "special_ability": "Iron Ball Form",
        "tier": "nu", "wins": 1, "losses": 5,
        "lore_background": "A tiny fortress on legs — rolling up was always the plan.",
        "lore_motivation": "Outlasting everyone by refusing to open up.",
        "lore_personality": "Passive, immovable, occasionally surprising.",
    },
    {
        "image_index": 5,
        "owner": "testuser3",
        "nickname": "Pincher Pete",
        "common_name": "Common Earwig",
        "scientific_name": "Forficula auricularia",
        "order": "Dermaptera",
        "family": "Forficulidae",
        "description": "Found scurrying from under a damp log. Wielded its forceps aggressively.",
        "location_found": "Decaying log pile",
        "attack": 52, "defense": 42, "speed": 62,
        "lethality": 48, "grip": 58, "cunning": 50,
        "attack_type": "piercing", "defense_type": "evasive",
        "size_class": "small",
        "special_ability": "Forceps Grab",
        "tier": "ru", "wins": 3, "losses": 3,
        "lore_background": "Feared for its cerci — underestimated for everything else.",
        "lore_motivation": "Fights to prove forceps aren't just defensive.",
        "lore_personality": "Aggressive, territorial, and surprisingly dexterous.",
    },
    {
        "image_index": 0,
        "owner": "testuser4",
        "nickname": "Daddy Long Reach",
        "common_name": "Daddy Longlegs",
        "scientific_name": "Phalangium opilio",
        "order": "Opiliones",
        "family": "Phalangiidae",
        "description": "Discovered in the corner of the garden shed. Alarmingly fast for its size.",
        "location_found": "Garden shed corner",
        "attack": 22, "defense": 28, "speed": 85,
        "lethality": 18, "grip": 20, "cunning": 78,
        "attack_type": "neutral", "defense_type": "evasive",
        "size_class": "small",
        "special_ability": "Leg Drop Escape",
        "tier": "nu", "wins": 2, "losses": 4,
        "lore_background": "All leg and no ego — outruns everything it can't outwit.",
        "lore_motivation": "Fights purely on movement and misdirection.",
        "lore_personality": "Skittish but weirdly confident about it.",
    },
    {
        "image_index": 1,
        "owner": "testuser4",
        "nickname": "Carpet Soldier",
        "common_name": "Carpenter Ant",
        "scientific_name": "Camponotus pennsylvanicus",
        "order": "Hymenoptera",
        "family": "Formicidae",
        "description": "A large black ant found hauling a wood chip three times its size.",
        "location_found": "Deck boards",
        "attack": 48, "defense": 52, "speed": 60,
        "lethality": 40, "grip": 68, "cunning": 55,
        "attack_type": "piercing", "defense_type": "segmented_armor",
        "size_class": "small",
        "special_ability": "Acid Spit",
        "tier": "ru", "wins": 4, "losses": 2,
        "lore_background": "One ant who left the colony to prove the individual could matter.",
        "lore_motivation": "Fights every battle like the colony is watching.",
        "lore_personality": "Methodical, relentless, chemically enhanced.",
    },
    {
        "image_index": 2,
        "owner": "backyard_benny",
        "nickname": "Rusty Fang",
        "common_name": "Garden Spider",
        "scientific_name": "Argiope aurantia",
        "order": "Araneae",
        "family": "Araneidae",
        "description": "Centre-stage in a dew-covered orb web at dawn.",
        "location_found": "Tomato plant wire",
        "attack": 62, "defense": 44, "speed": 56,
        "lethality": 70, "grip": 80, "cunning": 62,
        "attack_type": "venom", "defense_type": "evasive",
        "size_class": "medium",
        "special_ability": "Web Trap",
        "tier": "uu", "wins": 5, "losses": 3,
        "lore_background": "Wove its reputation one ambush at a time.",
        "lore_motivation": "Fights to show a grid of silk is worth more than a suit of armor.",
        "lore_personality": "Patient, precise, deeply territorial.",
    },
    {
        "image_index": 3,
        "owner": "backyard_benny",
        "nickname": "Slime General",
        "common_name": "Caterpillar",
        "scientific_name": "Lymantria dispar",
        "order": "Lepidoptera",
        "family": "Erebidae",
        "description": "A stout, hairy caterpillar found on an oak leaf. Surprisingly confrontational.",
        "location_found": "Oak tree branch",
        "attack": 25, "defense": 50, "speed": 15,
        "lethality": 30, "grip": 45, "cunning": 40,
        "attack_type": "chemical", "defense_type": "hairy_spiny",
        "size_class": "small",
        "special_ability": "Urticating Hairs",
        "tier": "nu", "wins": 1, "losses": 4,
        "lore_background": "One day it will have wings. Today it has hairs and spite.",
        "lore_motivation": "Fights to prove the larval form is already dangerous.",
        "lore_personality": "Slow, sticky, weirdly menacing up close.",
    },
    {
        "image_index": 4,
        "owner": "mod_mason",
        "nickname": "Hundred Knives",
        "common_name": "House Centipede",
        "scientific_name": "Scutigera coleoptrata",
        "order": "Scutigeromorpha",
        "family": "Scutigeridae",
        "description": "Spotted crossing the bathroom wall at 2am. Very fast. Very many legs.",
        "location_found": "Bathroom wall",
        "attack": 68, "defense": 35, "speed": 92,
        "lethality": 72, "grip": 55, "cunning": 60,
        "attack_type": "venom", "defense_type": "evasive",
        "size_class": "medium",
        "special_ability": "Leg Whip Barrage",
        "tier": "uu", "wins": 6, "losses": 2,
        "lore_background": "Evolved to be terrifying on purpose — speed and venom as theater.",
        "lore_motivation": "Every room it enters becomes its arena.",
        "lore_personality": "Theatrical, predatory, weirdly graceful.",
    },
    {
        "image_index": 5,
        "owner": "mod_mason",
        "nickname": "Bronze Shield",
        "common_name": "Ground Beetle",
        "scientific_name": "Carabus auratus",
        "order": "Coleoptera",
        "family": "Carabidae",
        "description": "Found under a flagstone — iridescent and annoyed.",
        "location_found": "Flagstone path",
        "attack": 55, "defense": 65, "speed": 58,
        "lethality": 45, "grip": 60, "cunning": 52,
        "attack_type": "crushing", "defense_type": "hard_shell",
        "size_class": "medium",
        "special_ability": "Mandible Vice",
        "tier": "ru", "wins": 3, "losses": 3,
        "lore_background": "Polished by generations of underground combat.",
        "lore_motivation": "Fights because above-ground is just a bigger arena.",
        "lore_personality": "Gritty, methodical, unreasonably shiny.",
    },
]
# fmt: on


# ─────────────────────────────────────────────────────────────────────────────
# Championship Circuit seed data
# ─────────────────────────────────────────────────────────────────────────────

# fmt: off
CIRCUIT_BUGS = [
    # ── ZU tier — active champion (3 defenses = Iron Reign) + 3 contenders ──
    {
        "image_index": 0, "owner": "testuser1",
        "nickname": "Void Mite", "common_name": "Grain Mite",
        "scientific_name": "Acarus siro", "order": "Trombidiformes", "family": "Acaridae",
        "description": "Microscopic terror from the flour bin. Invisible until it isn't.",
        "location_found": "Kitchen flour canister",
        "attack": 18, "defense": 22, "speed": 38, "lethality": 28, "grip": 15, "cunning": 45,
        "attack_type": "piercing", "defense_type": "evasive", "size_class": "tiny",
        "special_ability": "Colony Swarm", "tier": "zu", "wins": 8, "losses": 0,
        "circuit_role": "champion", "defense_count": 3,
        "lore_background": "Undefeated. Not because no one tries — because no one survives to report back.",
        "lore_motivation": "The bottom tier is its domain and it intends to keep it that way.",
        "lore_personality": "Patient, invisible, inevitable.",
    },
    {
        "image_index": 1, "owner": "testuser2",
        "nickname": "Rust Speck", "common_name": "Rust Mite",
        "scientific_name": "Panonychus ulmi", "order": "Trombidiformes", "family": "Tetranychidae",
        "description": "Found on a dying apple leaf, indignant about the whole situation.",
        "location_found": "Orchard apple tree",
        "attack": 16, "defense": 20, "speed": 42, "lethality": 22, "grip": 12, "cunning": 48,
        "attack_type": "piercing", "defense_type": "evasive", "size_class": "tiny",
        "special_ability": "Web Wrap", "tier": "zu", "wins": 6, "losses": 1,
        "circuit_role": "contender", "contender_rank": 1,
        "lore_background": "Came closest to toppling the champion. That one loss still stings.",
        "lore_motivation": "One rematch is all it needs.",
        "lore_personality": "Bitter, quick, relentless.",
    },
    {
        "image_index": 2, "owner": "testuser3",
        "nickname": "Pale Crawler", "common_name": "Clover Mite",
        "scientific_name": "Bryobia praetiosa", "order": "Trombidiformes", "family": "Tetranychidae",
        "description": "Found on a window ledge, heading nowhere in particular.",
        "location_found": "Bedroom window frame",
        "attack": 14, "defense": 18, "speed": 35, "lethality": 20, "grip": 10, "cunning": 40,
        "attack_type": "neutral", "defense_type": "evasive", "size_class": "tiny",
        "special_ability": "Red Stain Threat", "tier": "zu", "wins": 5, "losses": 2,
        "circuit_role": "contender", "contender_rank": 2,
        "callout_target": "Rust Speck",
        "lore_background": "Nobody expects pale. That's been the whole strategy.",
        "lore_motivation": "Called out Rust Speck publicly. Now it has to back it up.",
        "lore_personality": "Underrated on purpose.",
    },
    {
        "image_index": 3, "owner": "testuser4",
        "nickname": "Grit Larva", "common_name": "Soil Mite Larva",
        "scientific_name": "Oribatida specimen", "order": "Trombidiformes", "family": "Oribatidae",
        "description": "Dug out of compressed topsoil. Annoyed at everything.",
        "location_found": "Garden soil sample",
        "attack": 12, "defense": 25, "speed": 28, "lethality": 15, "grip": 20, "cunning": 35,
        "attack_type": "crushing", "defense_type": "segmented_armor", "size_class": "tiny",
        "special_ability": "Soil Anchor", "tier": "zu", "wins": 5, "losses": 3,
        "circuit_role": "contender", "contender_rank": 3,
        "lore_background": "Made of grit. Literally.",
        "lore_motivation": "Grind until the rankings move.",
        "lore_personality": "Stubborn, slow to anger, dangerous when cornered.",
    },

    # ── NU tier — champion (1 defense) + 2 contenders ────────────────────────
    {
        "image_index": 4, "owner": "collector_nova",
        "nickname": "Neon Pincer", "common_name": "Pseudoscorpion",
        "scientific_name": "Chelifer cancroides", "order": "Pseudoscorpiones", "family": "Cheliferidae",
        "description": "Found in an old book spine. Tiny, clawed, and furious.",
        "location_found": "Library bookshelf",
        "attack": 32, "defense": 28, "speed": 45, "lethality": 38, "grip": 42, "cunning": 55,
        "attack_type": "grappling", "defense_type": "evasive", "size_class": "tiny",
        "special_ability": "Book Scorpion Grip", "tier": "nu", "wins": 7, "losses": 1,
        "circuit_role": "champion", "defense_count": 1,
        "lore_background": "Smaller than a thumbtack. Fought things three times its size to get here.",
        "lore_motivation": "The NU belt is a stepping stone. Neon Pincer already has plans.",
        "lore_personality": "Methodical, surprisingly fast, grips like a vice.",
    },
    {
        "image_index": 5, "owner": "backyard_benny",
        "nickname": "Static Roach", "common_name": "German Cockroach",
        "scientific_name": "Blattella germanica", "order": "Blattodea", "family": "Ectobiidae",
        "description": "Found behind the fridge. Utterly fearless. Probably immortal.",
        "location_found": "Behind kitchen refrigerator",
        "attack": 30, "defense": 35, "speed": 62, "lethality": 32, "grip": 28, "cunning": 58,
        "attack_type": "neutral", "defense_type": "evasive", "size_class": "small",
        "special_ability": "Scatter Reflex", "tier": "nu", "wins": 6, "losses": 2,
        "circuit_role": "contender", "contender_rank": 1,
        "lore_background": "Survived every exterminator attempt. The arena is easy by comparison.",
        "lore_motivation": "Titles are just another thing it refuses to let kill it.",
        "lore_personality": "Impossibly durable, fast, and annoyingly smug.",
    },
    {
        "image_index": 0, "owner": "arena_jo",
        "nickname": "Mud Shrimp", "common_name": "Seed Shrimp",
        "scientific_name": "Ostracoda specimen", "order": "Ostracoda", "family": "Cyprididae",
        "description": "Fished from a stagnant puddle. No one took it seriously at first.",
        "location_found": "Puddle by the garden tap",
        "attack": 22, "defense": 38, "speed": 30, "lethality": 18, "grip": 35, "cunning": 42,
        "attack_type": "crushing", "defense_type": "hard_shell", "size_class": "tiny",
        "special_ability": "Bivalve Snap", "tier": "nu", "wins": 5, "losses": 2,
        "circuit_role": "contender", "contender_rank": 2,
        "lore_background": "Came from a puddle. Refuses to return to one.",
        "lore_motivation": "Prove the shell matters more than the size.",
        "lore_personality": "Quiet, defensive, devastating on a good day.",
    },

    # ── RU tier — champion (2 defenses) + 3 contenders + LOCKED title fight ──
    {
        "image_index": 1, "owner": "field_scout_rin",
        "nickname": "Iron Grub", "common_name": "Rhinoceros Beetle Larva",
        "scientific_name": "Dynastes tityus larva", "order": "Coleoptera", "family": "Scarabaeidae",
        "description": "Dug out of a rotting oak stump. Already massive. Already angry.",
        "location_found": "Rotting oak log, deep forest",
        "attack": 58, "defense": 72, "speed": 20, "lethality": 48, "grip": 80, "cunning": 32,
        "attack_type": "crushing", "defense_type": "thick_hide", "size_class": "large",
        "special_ability": "Mandible Lock", "tier": "ru", "wins": 9, "losses": 2,
        "circuit_role": "champion", "defense_count": 2,
        "lore_background": "Will become a Rhinoceros Beetle one day. For now it's already the biggest thing in its weight class.",
        "lore_motivation": "Two defenses in. The dynasty is just beginning.",
        "lore_personality": "Slow, immovable, grips with the force of a vice.",
    },
    {
        "image_index": 2, "owner": "mod_mason",
        "nickname": "Acid Wing", "common_name": "Bombardier Beetle",
        "scientific_name": "Brachinus crepitans", "order": "Coleoptera", "family": "Carabidae",
        "description": "Found under a log. Demonstrated its defense mechanism immediately.",
        "location_found": "Mossy woodland log",
        "attack": 62, "defense": 44, "speed": 55, "lethality": 70, "grip": 38, "cunning": 52,
        "attack_type": "chemical", "defense_type": "evasive", "size_class": "small",
        "special_ability": "Boiling Acid Blast", "tier": "ru", "wins": 7, "losses": 3,
        "circuit_role": "contender", "contender_rank": 1,
        "lore_background": "Can fire a boiling chemical spray at 100°C. The arena installed splash guards.",
        "lore_motivation": "The #1 ranking is fine. The belt would be better.",
        "lore_personality": "Volatile, precise, leaves a chemical trail.",
    },
    {
        "image_index": 3, "owner": "testuser1",
        "nickname": "Hook Jaw", "common_name": "Stag Beetle",
        "scientific_name": "Lucanus cervus", "order": "Coleoptera", "family": "Lucanidae",
        "description": "Found on an oak tree at dusk, mandibles already spread.",
        "location_found": "Ancient oak tree, evening",
        "attack": 70, "defense": 52, "speed": 38, "lethality": 55, "grip": 78, "cunning": 45,
        "attack_type": "grappling", "defense_type": "hard_shell", "size_class": "large",
        "special_ability": "Antler Lock", "tier": "ru", "wins": 6, "losses": 2,
        "circuit_role": "contender", "contender_rank": 2,
        "circuit_extra": "locked_challenger",
        "lore_background": "Has the biggest mandibles in its tier. Uses them like a grappling hook.",
        "lore_motivation": "The title fight is locked. Challenger confirmed. Time to finish the job.",
        "lore_personality": "Bold, physical, extraordinarily strong for its size.",
    },
    {
        "image_index": 4, "owner": "testuser2",
        "nickname": "Dusk Biter", "common_name": "Diving Beetle",
        "scientific_name": "Dytiscus marginalis", "order": "Coleoptera", "family": "Dytiscidae",
        "description": "Pulled from a garden pond at dusk. Bites through fingers.",
        "location_found": "Garden pond, twilight",
        "attack": 55, "defense": 48, "speed": 52, "lethality": 60, "grip": 44, "cunning": 48,
        "attack_type": "piercing", "defense_type": "hard_shell", "size_class": "medium",
        "special_ability": "Diving Assault", "tier": "ru", "wins": 5, "losses": 3,
        "circuit_role": "contender", "contender_rank": 3,
        "lore_background": "Equally at home in water and on land. The arena is just another pond.",
        "lore_motivation": "Third is a launching pad. The locked fight only proves it needs to work harder.",
        "lore_personality": "Adaptable, biting, refuses to stay down.",
    },

    # ── UU tier — champion (2 defenses) + 3 contenders + BIDDING OPEN ─────────
    {
        "image_index": 5, "owner": "collector_nova",
        "nickname": "Jade Stalker", "common_name": "Chinese Mantis",
        "scientific_name": "Tenodera sinensis", "order": "Mantodea", "family": "Mantidae",
        "description": "Spotted on a garden trellis at dawn, perfectly motionless.",
        "location_found": "Garden trellis, sunrise",
        "attack": 80, "defense": 52, "speed": 68, "lethality": 78, "grip": 62, "cunning": 72,
        "attack_type": "slashing", "defense_type": "evasive", "size_class": "large",
        "special_ability": "Raptorial Ambush", "tier": "uu", "wins": 10, "losses": 3,
        "circuit_role": "champion", "defense_count": 2,
        "lore_background": "Largest mantis in the arena. Two title defenses in, still undefeated in title bouts.",
        "lore_motivation": "The belt belongs to the mantis. It intends to prove this indefinitely.",
        "lore_personality": "Calm under pressure, terrifyingly fast when moving.",
    },
    {
        "image_index": 0, "owner": "field_scout_rin",
        "nickname": "Crimson Scythe", "common_name": "Red Assassin Bug",
        "scientific_name": "Rhodnius prolixus", "order": "Hemiptera", "family": "Reduviidae",
        "description": "Found on a stem, probing with its rostrum like a tiny predator.",
        "location_found": "Tall grass meadow",
        "attack": 72, "defense": 45, "speed": 74, "lethality": 80, "grip": 48, "cunning": 62,
        "attack_type": "piercing", "defense_type": "evasive", "size_class": "small",
        "special_ability": "Rostrum Strike", "tier": "uu", "wins": 8, "losses": 2,
        "circuit_role": "contender", "contender_rank": 1,
        "circuit_extra": "bid_rank1",
        "lore_background": "Rank 1. The title shot bid is free for a reason — this one already earned it.",
        "lore_motivation": "The champion is next. The bid was just paperwork.",
        "lore_personality": "Precise, aggressive, strikes from distance.",
    },
    {
        "image_index": 1, "owner": "arena_jo",
        "nickname": "Night Veil", "common_name": "Bark Louse",
        "scientific_name": "Polypsocus corruptus", "order": "Psocodea", "family": "Polypsocidae",
        "description": "Found under bark at night, camouflaged so well it nearly wasn't found.",
        "location_found": "Dead birch bark",
        "attack": 45, "defense": 58, "speed": 70, "lethality": 48, "grip": 40, "cunning": 75,
        "attack_type": "neutral", "defense_type": "evasive", "size_class": "small",
        "special_ability": "Bark Camouflage", "tier": "uu", "wins": 7, "losses": 3,
        "circuit_role": "contender", "contender_rank": 2,
        "circuit_extra": "bid_rank2",
        "lore_background": "Almost invisible in its natural habitat. The arena had to paint the arena floor white.",
        "lore_motivation": "Bid 75 AP for the shot. Wants it badly.",
        "lore_personality": "Stealthy, patient, disorienting to fight.",
    },
    {
        "image_index": 2, "owner": "testuser3",
        "nickname": "Obsidian Claw", "common_name": "Rove Beetle",
        "scientific_name": "Staphylinus olens", "order": "Coleoptera", "family": "Staphylinidae",
        "description": "Found in compost. Much faster and meaner than expected.",
        "location_found": "Compost heap, deep layer",
        "attack": 65, "defense": 50, "speed": 62, "lethality": 58, "grip": 55, "cunning": 50,
        "attack_type": "piercing", "defense_type": "hard_shell", "size_class": "medium",
        "special_ability": "Devil's Coach Horse Display", "tier": "uu", "wins": 6, "losses": 3,
        "circuit_role": "contender", "contender_rank": 3,
        "circuit_extra": "bid_rank3",
        "lore_background": "Bid 200 AP for the title shot — highest bid on the table. Wants that belt.",
        "lore_motivation": "Spent the AP. Now has to earn it back with a championship.",
        "lore_personality": "Aggressive, intimidating posture, bites first.",
    },

    # ── OU tier — VACANT belt, 2 contenders ──────────────────────────────────
    {
        "image_index": 3, "owner": "mod_mason",
        "nickname": "Ember Drake", "common_name": "Fire Beetle",
        "scientific_name": "Pyrophorus noctilucus", "order": "Coleoptera", "family": "Elateridae",
        "description": "A bioluminescent click beetle found near a bonfire. Glows orange.",
        "location_found": "Bonfire clearing, midnight",
        "attack": 78, "defense": 58, "speed": 62, "lethality": 72, "grip": 55, "cunning": 68,
        "attack_type": "electric", "defense_type": "bioluminescent", "size_class": "medium",
        "special_ability": "Click Launch", "tier": "ou", "wins": 8, "losses": 1,
        "circuit_role": "contender", "contender_rank": 1,
        "lore_background": "The OU belt is vacant. Ember Drake is the front-runner and knows it.",
        "lore_motivation": "First champion of the OU tier. That's the goal.",
        "lore_personality": "Electric, dramatic, lights up when threatened.",
    },
    {
        "image_index": 4, "owner": "testuser4",
        "nickname": "Thunder Grub", "common_name": "Click Beetle Larva",
        "scientific_name": "Agriotes lineatus larva", "order": "Coleoptera", "family": "Elateridae",
        "description": "Found in the soil near a lawn. Deceptively powerful for a larva.",
        "location_found": "Lawn root zone",
        "attack": 72, "defense": 62, "speed": 45, "lethality": 65, "grip": 70, "cunning": 50,
        "attack_type": "crushing", "defense_type": "hard_shell", "size_class": "medium",
        "special_ability": "Root Spike", "tier": "ou", "wins": 7, "losses": 2,
        "circuit_role": "contender", "contender_rank": 2,
        "lore_background": "Ember Drake got rank 1. Thunder Grub is making a case for why that was a mistake.",
        "lore_motivation": "Unseat the favourite. Take the inaugural belt.",
        "lore_personality": "Methodical, grinding, doesn't celebrate until the fight is over.",
    },

    # ── Uber tier — VACANT belt, 1 contender (not enough for a fight yet) ─────
    {
        "image_index": 5, "owner": "testuser1",
        "nickname": "Apex Phantom", "common_name": "Giant Water Bug",
        "scientific_name": "Lethocerus americanus", "order": "Hemiptera", "family": "Belostomatidae",
        "description": "Found in a still pond at night. Eats frogs. The arena made special rules.",
        "location_found": "Still farm pond, after dark",
        "attack": 92, "defense": 65, "speed": 58, "lethality": 90, "grip": 88, "cunning": 62,
        "attack_type": "piercing", "defense_type": "thick_hide", "size_class": "large",
        "special_ability": "Toe-Biter Ambush", "tier": "uber", "wins": 9, "losses": 2,
        "circuit_role": "contender", "contender_rank": 1,
        "lore_background": "Only contender at Uber. Waiting for someone else to be brave enough.",
        "lore_motivation": "The belt will exist when there's someone worth taking it from.",
        "lore_personality": "Apex predator. Quiet about it.",
    },
]

SEASON_BUGS = [
    # ── OU season track bugs — 5 competitors for the standings tab ────────────
    {
        "image_index": 0, "owner": "mod_mason",
        "nickname": "Oak Sentry", "common_name": "Great Diving Beetle",
        "scientific_name": "Dytiscus marginalis adult", "order": "Coleoptera", "family": "Dytiscidae",
        "description": "An elite-tier season veteran from the forest pool.",
        "location_found": "Forest pool",
        "attack": 74, "defense": 62, "speed": 52, "lethality": 68, "grip": 58, "cunning": 55,
        "attack_type": "piercing", "defense_type": "hard_shell", "size_class": "large",
        "special_ability": "Submerge Ambush", "tier": "ou", "wins": 6, "losses": 2,
        "bug_track": "season", "season_wins": 4, "season_losses": 2,
        "lore_background": "An OU season mainstay with a strong regular-season record.",
        "lore_motivation": "The season trophy before retirement.",
        "lore_personality": "Experienced, reads opponents well.",
    },
    {
        "image_index": 1, "owner": "testuser1",
        "nickname": "Thorn Rush", "common_name": "Thornbug",
        "scientific_name": "Umbonia crassicornis", "order": "Hemiptera", "family": "Membracidae",
        "description": "Found on a rose stem — indistinguishable from a thorn until it moved.",
        "location_found": "Rose bush, stem junction",
        "attack": 65, "defense": 70, "speed": 60, "lethality": 58, "grip": 52, "cunning": 62,
        "attack_type": "piercing", "defense_type": "hairy_spiny", "size_class": "small",
        "special_ability": "Thorn Camouflage", "tier": "ou", "wins": 4, "losses": 1,
        "bug_track": "season", "season_wins": 3, "season_losses": 1,
        "lore_background": "Unbeaten in three season matches. The dark horse of OU.",
        "lore_motivation": "Nobody guesses a thorn is dangerous twice.",
        "lore_personality": "Deceptive, patient, suddenly devastating.",
    },
    {
        "image_index": 2, "owner": "testuser2",
        "nickname": "Amber Gate", "common_name": "Golden Tortoise Beetle",
        "scientific_name": "Charidotella sexpunctata", "order": "Coleoptera", "family": "Chrysomelidae",
        "description": "Shines gold in sunlight. Has an attitude to match.",
        "location_found": "Morning glory vine",
        "attack": 55, "defense": 75, "speed": 48, "lethality": 45, "grip": 60, "cunning": 58,
        "attack_type": "neutral", "defense_type": "hard_shell", "size_class": "small",
        "special_ability": "Mirror Shield", "tier": "ou", "wins": 4, "losses": 4,
        "bug_track": "season", "season_wins": 2, "season_losses": 2,
        "lore_background": "Won't win the season but won't go quietly either.",
        "lore_motivation": "Make the bracket miserable for whoever faces it.",
        "lore_personality": "Defensive, frustrating to crack, gleaming.",
    },
    {
        "image_index": 3, "owner": "testuser3",
        "nickname": "Stone Bastion", "common_name": "Net-Winged Beetle",
        "scientific_name": "Calopteron reticulatum", "order": "Coleoptera", "family": "Lycidae",
        "description": "Bright orange and black warning colours. The arena treats them seriously.",
        "location_found": "Decaying forest debris",
        "attack": 50, "defense": 68, "speed": 45, "lethality": 55, "grip": 48, "cunning": 52,
        "attack_type": "chemical", "defense_type": "toxic_skin", "size_class": "medium",
        "special_ability": "Warning Aposematism", "tier": "ou", "wins": 3, "losses": 3,
        "bug_track": "season", "season_wins": 3, "season_losses": 3,
        "lore_background": "Mid-table this season. Survived every fight it was supposed to lose.",
        "lore_motivation": "Stay in the league. Prove chemical defense belongs in OU.",
        "lore_personality": "Stubborn, durable, chemically protected.",
    },
    {
        "image_index": 4, "owner": "testuser4",
        "nickname": "Spark Runner", "common_name": "Click Beetle",
        "scientific_name": "Agriotes obscurus", "order": "Coleoptera", "family": "Elateridae",
        "description": "Found on a fence post. Flipped itself upright three times in a row when startled.",
        "location_found": "Old fence post",
        "attack": 58, "defense": 48, "speed": 72, "lethality": 50, "grip": 42, "cunning": 62,
        "attack_type": "electric", "defense_type": "evasive", "size_class": "small",
        "special_ability": "Click Escape", "tier": "ou", "wins": 1, "losses": 3,
        "bug_track": "season", "season_wins": 1, "season_losses": 3,
        "lore_background": "Bottom of the table. Still clicking.",
        "lore_motivation": "One upset win would change everything.",
        "lore_personality": "Erratic, unpredictable, occasionally brilliant.",
    },
]
# fmt: on

_CIRCUIT_NICKNAMES = {b["nickname"] for b in CIRCUIT_BUGS}
_SEASON_NICKNAMES = {b["nickname"] for b in SEASON_BUGS}

# Battles to create for circuit bugs (establishes narrative history)
_CIRCUIT_BATTLES = [
    # ZU championship history
    ("Void Mite",   "Rust Speck",   "Void Mite",   "dominant",  "The Flour Bin",
     "Void Mite defended its belt in the smallest arena ever recorded. Rust Speck never found an opening."),
    ("Void Mite",   "Pale Crawler", "Void Mite",   "contested", "The Window Frame",
     "The closest fight for the ZU champion yet. Pale Crawler pushed it to the limit before faltering."),
    # NU history
    ("Neon Pincer", "Static Roach", "Neon Pincer", "nail_biter","The Bookshelf",
     "The cockroach's speed almost won it. The pseudoscorpion's grip was the difference."),
    # RU championship history + upcoming fight setup
    ("Iron Grub",   "Acid Wing",    "Iron Grub",   "dominant",  "The Rotting Log",
     "Acid Wing's chemical blast dissolved against Iron Grub's hide. Unstoppable."),
    ("Hook Jaw",    "Dusk Biter",   "Hook Jaw",    "contested", "The Pond Edge",
     "Hook Jaw locked its mandibles. Dusk Biter nearly escaped but the grip held."),
    # UU championship
    ("Jade Stalker","Crimson Scythe","Jade Stalker","nail_biter","The Garden Trellis",
     "The red assassin bug came the closest of any challenger. Jade Stalker survived by a strike width."),
    ("Night Veil",  "Obsidian Claw","Night Veil",  "upset",     "The Bark Flat",
     "Night Veil vanished mid-fight and reappeared behind Obsidian Claw. Classic."),
    # OU contenders establishing records
    ("Ember Drake", "Thunder Grub", "Ember Drake", "contested", "The Bonfire Clearing",
     "A preview of what could be the inaugural OU title fight. Ember Drake edges it on the night."),
]

# Season battles for OU standings
_SEASON_BATTLES = [
    ("Oak Sentry",  "Stone Bastion","Oak Sentry",  "dominant",  "The Forest Pool",
     "Oak Sentry's diving ambush left Stone Bastion unable to respond."),
    ("Thorn Rush",  "Spark Runner", "Thorn Rush",  "dominant",  "The Rose Trellis",
     "Spark Runner clicked itself into a corner. Thorn Rush was already there waiting."),
    ("Amber Gate",  "Stone Bastion","Amber Gate",  "contested", "The Morning Glory",
     "Two defensive beetles. Neither could crack the other cleanly. Amber Gate wins on aggression."),
    ("Oak Sentry",  "Spark Runner", "Oak Sentry",  "dominant",  "The Deep Pool",
     "Dive, pin, done. Spark Runner had no answer for the ambush specialist."),
    ("Thorn Rush",  "Amber Gate",   "Thorn Rush",  "nail_biter","The Stem Row",
     "Amber Gate's mirror shield bought time but Thorn Rush's camouflage strike was too precise."),
    ("Stone Bastion","Spark Runner","Stone Bastion","contested","The Log Pile",
     "Spark Runner's speed was neutralised by the chemical warning display. Stone Bastion holds on."),
]


def seed_circuit_data(users: dict, positives: list[Path], upload_dir: Path) -> None:
    """Seed Championship Circuit: champions, contenders, title fights, bids, callouts, season."""
    now = datetime.utcnow()

    # ── 1. Create circuit bugs ────────────────────────────────────────────────
    def _make_bug(spec: dict) -> Bug:
        source = positives[spec["image_index"] % len(positives)]
        image_path = copy_sample_image(source, upload_dir, spec["nickname"])
        owner = users[spec["owner"]]
        scientific = spec["scientific_name"]
        species = Species.query.filter_by(scientific_name=scientific).first()
        if not species:
            species = Species(scientific_name=scientific, common_name=spec["common_name"],
                              order=spec["order"], family=spec["family"], data_source="sample_seed")
            db.session.add(species)
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
        bug.lethality = spec.get("lethality", 50)
        bug.grip = spec.get("grip", 50)
        bug.cunning = spec.get("cunning", 50)
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
        bug.bug_track = spec.get("bug_track", "mma")
        bug.stats_generated = True
        bug.stats_generation_method = "sample_seed"
        bug.vision_verified = True
        bug.vision_confidence = 0.97
        bug.is_verified = True
        bug.enrichment_status = "complete"
        bug.submission_date = now - timedelta(days=spec["image_index"] * 3 + 10)
        bug.generate_flair()
        return bug

    circuit_bugs = [_make_bug(s) for s in CIRCUIT_BUGS]
    season_bugs  = [_make_bug(s) for s in SEASON_BUGS]
    db.session.flush()

    by_name = {b.nickname: b for b in circuit_bugs + season_bugs}

    # ── 2. Circuit battles (history) ─────────────────────────────────────────
    for b1n, b2n, wn, rating, venue, narrative in _CIRCUIT_BATTLES + _SEASON_BATTLES:
        b1 = by_name.get(b1n)
        b2 = by_name.get(b2n)
        w  = by_name.get(wn)
        if not (b1 and b2 and w):
            continue
        if not Battle.query.filter_by(bug1_id=b1.id, bug2_id=b2.id, narrative=narrative).first():
            db.session.add(Battle(
                bug1_id=b1.id, bug2_id=b2.id, winner_id=w.id,
                narrative=narrative, venue=venue, battle_rating=rating,
                battle_date=now - timedelta(days=14 + len(narrative) % 30),
            ))
    db.session.flush()

    # ── 3. TierChampionship records ──────────────────────────────────────────
    def _get_or_create_belt(tier: str) -> TierChampionship:
        belt = TierChampionship.query.filter_by(tier=tier).first()
        if not belt:
            belt = TierChampionship(tier=tier, status="vacant")
            db.session.add(belt)
        return belt

    champions_by_tier: dict[str, Bug] = {}
    for spec in CIRCUIT_BUGS:
        if spec.get("circuit_role") == "champion":
            bug = by_name[spec["nickname"]]
            belt = _get_or_create_belt(spec["tier"])
            belt.champion_bug_id = bug.id
            belt.status = "active"
            belt.defense_count = spec["defense_count"]
            belt.won_date = now - timedelta(days=60)
            belt.next_defense_due = now + timedelta(days=30)
            champions_by_tier[spec["tier"]] = bug
            # Achievement badges
            _give_achievement(bug, "circuit_champion", "🏆 Circuit Champion",
                              "Holds an active Championship Circuit belt.", "legendary")
            if spec["defense_count"] >= 1:
                _give_achievement(bug, "first_defense", "🛡️ First Defense",
                                  "Successfully defended the belt once.", "rare")
            if spec["defense_count"] >= 3:
                _give_achievement(bug, "iron_reign", "⛓️ Iron Reign",
                                  "Defended the title three or more times.", "epic")

    # Ensure vacant belts exist for OU and Uber
    for t in ("ou", "uber"):
        belt = _get_or_create_belt(t)
        if belt.status != "active":
            belt.status = "vacant"
            belt.champion_bug_id = None

    db.session.flush()

    # ── 4. TierRanking records ───────────────────────────────────────────────
    for spec in CIRCUIT_BUGS:
        if spec.get("circuit_role") != "contender":
            continue
        bug = by_name[spec["nickname"]]
        rank = spec["contender_rank"]
        wins, losses = bug.wins, bug.losses
        total = wins + losses
        wr = wins / total if total > 0 else 0.0
        score = round(160.0 - rank * 15.0 + wr * 60.0, 1)

        ranking = TierRanking.query.filter_by(bug_id=bug.id, tier=spec["tier"]).first()
        if not ranking:
            ranking = TierRanking(bug_id=bug.id, tier=spec["tier"])
            db.session.add(ranking)
        ranking.rank = rank
        ranking.ranking_score = score
        ranking.last_updated = now
        ranking.last_fight_date = now - timedelta(days=rank * 5)

        # Contender achievements
        if rank == 1:
            _give_achievement(bug, "contender_no1", "🥇 #1 Contender",
                              "Reached the #1 contender spot in a tier.", "rare")
        elif rank <= 3:
            _give_achievement(bug, "contender_top3", "🥉 Top 3 Contender",
                              "Ranked in the top 3 contenders in a tier.", "uncommon")

    db.session.flush()

    # ── 5. Title fights ──────────────────────────────────────────────────────
    # UU — BIDDING OPEN (bid window closes in 3 days, fight in 30)
    uu_belt = TierChampionship.query.filter_by(tier="uu").first()
    uu_fight = TitleFight.query.filter_by(tier="uu", status="bidding").first()
    if not uu_fight and uu_belt:
        uu_fight = TitleFight(
            tier="uu",
            championship_id=uu_belt.id,
            scheduled_date=now + timedelta(days=30),
            bid_closes_at=now + timedelta(days=3),
            status="bidding",
            created_at=now - timedelta(days=2),
        )
        db.session.add(uu_fight)
        db.session.flush()

    # UU bids
    if uu_fight:
        _bid_data = [
            ("Crimson Scythe",  1, 0,    0),    # rank 1: free
            ("Night Veil",      2, 50,   75),   # rank 2: min 50, bid 75
            ("Obsidian Claw",   3, 150,  200),  # rank 3: min 150, bid 200 (highest)
        ]
        for nickname, c_rank, min_bid, amount in _bid_data:
            bug = by_name.get(nickname)
            if not bug:
                continue
            if not TitleBid.query.filter_by(fight_id=uu_fight.id, bug_id=bug.id).first():
                db.session.add(TitleBid(
                    fight_id=uu_fight.id,
                    bug_id=bug.id,
                    user_id=bug.user_id,
                    amount=amount,
                    contender_rank=c_rank,
                    min_required=min_bid,
                    placed_at=now - timedelta(hours=c_rank * 8),
                    won_bid=False,
                ))

    # RU — LOCKED (challenger confirmed, fight in 7 days)
    ru_belt = TierChampionship.query.filter_by(tier="ru").first()
    ru_fight = TitleFight.query.filter_by(tier="ru", status="locked").first()
    hook_jaw = by_name.get("Hook Jaw")
    if not ru_fight and ru_belt and hook_jaw:
        ru_fight = TitleFight(
            tier="ru",
            championship_id=ru_belt.id,
            challenger_bug_id=hook_jaw.id,
            scheduled_date=now + timedelta(days=7),
            bid_closes_at=now - timedelta(days=3),  # bidding already closed
            status="locked",
            created_at=now - timedelta(days=10),
        )
        db.session.add(ru_fight)

    db.session.flush()

    # ── 6. Contender callouts ────────────────────────────────────────────────
    # ZU: Pale Crawler (#2) calls out Rust Speck (#1)
    pale = by_name.get("Pale Crawler")
    rust = by_name.get("Rust Speck")
    if pale and rust:
        if not ContenderCallout.query.filter_by(
            tier="zu", challenger_bug_id=pale.id, target_bug_id=rust.id, status="pending"
        ).first():
            db.session.add(ContenderCallout(
                tier="zu",
                challenger_bug_id=pale.id,
                target_bug_id=rust.id,
                status="pending",
                created_at=now - timedelta(days=2),
                expires_at=now + timedelta(days=5),
            ))

    # NU: Mud Shrimp (#2) calls out Static Roach (#1)
    mud   = by_name.get("Mud Shrimp")
    roach = by_name.get("Static Roach")
    if mud and roach:
        if not ContenderCallout.query.filter_by(
            tier="nu", challenger_bug_id=mud.id, target_bug_id=roach.id, status="pending"
        ).first():
            db.session.add(ContenderCallout(
                tier="nu",
                challenger_bug_id=mud.id,
                target_bug_id=roach.id,
                status="pending",
                created_at=now - timedelta(days=1),
                expires_at=now + timedelta(days=6),
            ))

    db.session.flush()

    # ── 7. OU season standings ───────────────────────────────────────────────
    season_key = "elite_spring_2026_ou"
    season = Season.query.filter_by(season_key=season_key).first()
    if not season:
        season = Season(
            name="Elite Season — Spring 2026",
            tier="ou",
            season_key=season_key,
            phase="regular_season",
            registration_opens=now - timedelta(days=30),
            registration_closes=now - timedelta(days=20),
            regular_season_start=now - timedelta(days=18),
            regular_season_end=now + timedelta(days=30),
            max_registrations=16,
        )
        db.session.add(season)
        db.session.flush()

    for spec in SEASON_BUGS:
        bug = by_name.get(spec["nickname"])
        if not bug:
            continue
        reg = SeasonRegistration.query.filter_by(season_id=season.id, bug_id=bug.id).first()
        if not reg:
            reg = SeasonRegistration(
                season_id=season.id,
                bug_id=bug.id,
                user_id=bug.user_id,
                status="active",
            )
            db.session.add(reg)
        reg.season_wins = spec.get("season_wins", 0)
        reg.season_losses = spec.get("season_losses", 0)

    db.session.commit()
    print(f"  Circuit: {len(circuit_bugs)} MMA bugs, {len(season_bugs)} season bugs")
    print(f"  Belts: ZU/NU/RU/UU active champions, OU/Uber vacant")
    print(f"  Title fights: UU bidding (closes +3d), RU locked (fight +7d)")
    print(f"  Callouts: ZU #2→#1 (pending), NU #2→#1 (pending)")
    print(f"  Season: {season.name}")


def _give_achievement(bug: Bug, atype: str, name: str, desc: str, rarity: str) -> None:
    if not BugAchievement.query.filter_by(bug_id=bug.id, achievement_type=atype).first():
        icon = {"circuit_champion": "🏆", "first_defense": "🛡️", "iron_reign": "⛓️",
                "contender_no1": "🥇", "contender_top3": "🥉"}.get(atype, "🏅")
        db.session.add(BugAchievement(
            bug_id=bug.id,
            achievement_type=atype,
            achievement_name=name,
            achievement_icon=icon,
            description=desc,
            rarity=rarity,
        ))


def reset_circuit_data() -> None:
    all_nicknames = list(_CIRCUIT_NICKNAMES | _SEASON_NICKNAMES)
    circuit_bugs = Bug.query.filter(Bug.nickname.in_(all_nicknames)).all()
    bug_ids = [b.id for b in circuit_bugs]

    # Clean up circuit-specific tables first
    if bug_ids:
        ContenderCallout.query.filter(
            (ContenderCallout.challenger_bug_id.in_(bug_ids)) |
            (ContenderCallout.target_bug_id.in_(bug_ids))
        ).delete(synchronize_session=False)

        TitleBid.query.filter(TitleBid.bug_id.in_(bug_ids)).delete(synchronize_session=False)

        # Get fight IDs for these bugs' tiers to clean title fights
        tiers = list({b.tier for b in circuit_bugs if b.tier})
        TitleFight.query.filter(TitleFight.tier.in_(tiers)).delete(synchronize_session=False)
        TierRanking.query.filter(TierRanking.bug_id.in_(bug_ids)).delete(synchronize_session=False)
        TierChampionship.query.filter(TierChampionship.tier.in_(tiers)).delete(synchronize_session=False)

        Battle.query.filter(
            (Battle.bug1_id.in_(bug_ids)) | (Battle.bug2_id.in_(bug_ids))
        ).delete(synchronize_session=False)
        BugAchievement.query.filter(BugAchievement.bug_id.in_(bug_ids)).delete(synchronize_session=False)
        SeasonRegistration.query.filter(SeasonRegistration.bug_id.in_(bug_ids)).delete(synchronize_session=False)

    Season.query.filter_by(season_key="elite_spring_2026_ou").delete()

    if bug_ids:
        Bug.query.filter(Bug.id.in_(bug_ids)).delete(synchronize_session=False)

    db.session.commit()
    print("Circuit data reset.")


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
    bug.lethality = spec.get("lethality", 50)
    bug.grip = spec.get("grip", 50)
    bug.cunning = spec.get("cunning", 50)
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
    bug.submission_date = datetime.utcnow() - timedelta(days=spec["image_index"] * 2 + 1)
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
    # Index bugs by nickname for easy lookup
    by_name = {b.nickname: b for b in bugs}

    comments = [
        ("Ironclad Thorn",    "field_scout_rin", "That shell is doing real bracket work."),
        ("Verdant Hook",      "collector_nova",  "The posture alone deserves a seed."),
        ("Amber Needle",      "arena_jo",        "Fast, rude, and probably correct about it."),
        ("Sir Stinks-a-Lot",  "collector_nova",  "The smell is a real mechanic. I've seen it confuse faster bugs."),
        ("Lucky Seven",       "field_scout_rin", "Don't be fooled by the size. That reflex bleed is nasty."),
        ("The Chirper",       "arena_jo",        "Sonic type hitting evasive opponents is terrifying."),
        ("Ember Scout",       "testuser1",       "Bioluminescent in The Night Garden arena? Untouchable."),
        ("Rollie McRoll",     "testuser2",       "My money is always on the pillbug to outlast everything."),
        ("Hundred Knives",    "testuser3",       "I physically cannot watch this one fight. The legs."),
        ("Rusty Fang",        "backyard_benny",  "The grip stat on this spider is insane. Nothing escapes."),
        ("Carpet Soldier",    "testuser4",       "Acid spit on a segmented armor bug is underrated."),
        ("Pincher Pete",      "mod_mason",       "Forceps grab into piercing damage — ruthless combo."),
    ]
    for name, uname, text in comments:
        bug = by_name.get(name)
        user = users.get(uname)
        if bug and user and not Comment.query.filter_by(bug_id=bug.id, user_id=user.id, text=text).first():
            db.session.add(Comment(text=text, bug_id=bug.id, user_id=user.id, upvotes=1))

    lore_entries = [
        ("Ironclad Thorn",   "arena_jo",       "Arena rumor says Ironclad Thorn sleeps inside a split acorn helmet."),
        ("Eight-Eye Static", "collector_nova", "Eight-Eye Static once vanished mid-stare and reappeared on the judge's clipboard."),
        ("Goliath Rootsplitter", "mod_mason",  "Goliath Rootsplitter refuses to fight indoors after cracking a practice tile."),
        ("Sir Stinks-a-Lot", "testuser2",      "Local legend: a whole matchup was called off because the referee couldn't take the smell."),
        ("Lucky Seven",      "testuser3",      "Seven spots. Seven wins against bugs twice its size. Coincidence? Ask the losers."),
        ("The Chirper",      "backyard_benny", "There are reports of rivals tapping out just from the pre-fight chirping."),
        ("Ember Scout",      "testuser1",      "Eyewitnesses say its flash timing is almost musical. Eerie to watch."),
        ("Hundred Knives",   "field_scout_rin","Someone once said counting its legs before a fight broke their concentration completely."),
    ]
    for name, uname, text in lore_entries:
        bug = by_name.get(name)
        user = users.get(uname)
        if bug and user and not BugLore.query.filter_by(bug_id=bug.id, user_id=user.id, lore_text=text).first():
            db.session.add(BugLore(lore_text=text, bug_id=bug.id, user_id=user.id, upvotes=2))


def add_battles_and_tournament(bugs: list[Bug], users: dict[str, User], owner: User) -> None:
    by_name = {b.nickname: b for b in bugs}

    pairings = [
        # Power matchups
        ("Ironclad Thorn",    "Eight-Eye Static",  "Ironclad Thorn",    "dominant",  "The Garden Stone",
         "Ironclad Thorn absorbed every leap before ending the bout with a grinding charge."),
        ("Verdant Hook",      "Dustwing Hex",       "Verdant Hook",      "dominant",  "The Leaf Pile",
         "Verdant Hook waited through a cloud of dust, then cut the match short."),
        ("Amber Needle",      "Goliath Rootsplitter","Amber Needle",     "upset",     "The Fence Post",
         "Amber Needle survived the opening crash and won by never standing still."),
        # Common bug matchups
        ("Sir Stinks-a-Lot",  "Lucky Seven",        "Sir Stinks-a-Lot", "contested", "The Flower Bed",
         "Two chemical fighters. The stink bug's heavier armor made the difference."),
        ("The Chirper",       "Rollie McRoll",      "The Chirper",      "nail_biter","The Garage Floor",
         "Sonic resonance on segmented armor is punishing. The cricket knew exactly where to chirp."),
        ("Ember Scout",       "Daddy Long Reach",   "Ember Scout",      "contested", "The Night Garden",
         "In the dark, the firefly's disorienting flash erased every speed advantage."),
        ("Pincher Pete",      "Carpet Soldier",     "Carpet Soldier",   "contested", "The Rotting Log",
         "Forceps met mandibles. The carpenter ant's acid spit eventually found purchase."),
        ("Hundred Knives",    "Rusty Fang",         "Hundred Knives",   "nail_biter","The Windowsill",
         "Two venomous predators — the centipede's speed proved the tiebreaker."),
        ("Bronze Shield",     "Slime General",      "Bronze Shield",    "dominant",  "The Mud Flat",
         "Hard shell against hairy defense. The ground beetle's mandible grip was decisive."),
        # Upsets and surprises
        ("Lucky Seven",       "Sir Stinks-a-Lot",   "Lucky Seven",      "upset",     "The Birdbath Edge",
         "Rematch. This time the ladybug's reflex bleed turned a loss into a draw-by-attrition."),
        ("Rollie McRoll",     "Slime General",      "Rollie McRoll",    "nail_biter","The Compost Heap",
         "Neither bug has much offence. The pillbug simply outlasted every chemical barrage."),
    ]

    for b1_name, b2_name, winner_name, rating, venue, narrative in pairings:
        b1 = by_name.get(b1_name)
        b2 = by_name.get(b2_name)
        winner = by_name.get(winner_name)
        if not b1 or not b2 or not winner:
            continue
        existing = Battle.query.filter_by(bug1_id=b1.id, bug2_id=b2.id, narrative=narrative).first()
        if not existing:
            db.session.add(Battle(
                bug1_id=b1.id,
                bug2_id=b2.id,
                winner_id=winner.id,
                narrative=narrative,
                battle_date=datetime.utcnow() - timedelta(days=len(narrative) % 14 + 1),
                venue=venue,
                battle_rating=rating,
            ))
            award_battle_achievements(winner, b2 if winner.id == b1.id else b1)

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
            round_number=1, match_number=1,
            bug1_id=bugs[0].id, bug2_id=bugs[1].id,
        ))
        db.session.add(TournamentMatch(
            tournament_id=tournament.id,
            round_number=1, match_number=2,
            bug1_id=bugs[2].id, bug2_id=bugs[3].id,
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
    parser.add_argument("--circuit", action="store_true", help="Seed Championship Circuit test data (bugs, fights, rankings).")
    parser.add_argument("--reset-circuit", action="store_true", help="Remove existing circuit data before seeding.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.create_schema:
            db.create_all()

        if args.reset_sample:
            reset_sample_data()

        if args.reset_circuit:
            reset_circuit_data()

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
        add_battles_and_tournament(bugs, users, users["owner_ivy"])
        db.session.commit()

        if args.circuit:
            seed_circuit_data(users, positives, Path(app.config["UPLOAD_FOLDER"]))
            db.session.commit()

        write_manifest(positives, negatives, Path(args.manifest))

        print("Seeded sample users (password: battlebugs):")
        for spec in SAMPLE_USERS:
            print(f"  {spec['username']:25s} ({spec['role']})")
        print(f"\nSeeded {len(bugs)} bugs from {args.positive_dir}")
        print(f"Recorded {len(negatives)} negative submission references")
        print(f"Manifest: {args.manifest}")
        if args.circuit:
            print("\nChampionship Circuit data seeded.")


if __name__ == "__main__":
    main()
