from datetime import datetime

from app import db
from app.models import Bug, BugAchievement
from app.services.economy import (
    ACHIEVEMENT_REWARDS,
    SUBMISSION_REWARD,
    UNIQUE_SPECIES_REWARD,
    award_currency,
)


def award_achievement(bug, achievement_type: str, name: str, icon: str, description: str, rarity: str = 'common') -> bool:
    existing = BugAchievement.query.filter_by(
        bug_id=bug.id,
        achievement_type=achievement_type,
    ).first()
    if existing:
        return False

    achievement = BugAchievement(
        bug_id=bug.id,
        achievement_type=achievement_type,
        achievement_name=name,
        achievement_icon=icon,
        description=description,
        rarity=rarity,
    )
    db.session.add(achievement)
    award_currency(
        bug.owner,
        ACHIEVEMENT_REWARDS.get(achievement_type, 0),
        f'achievement:{achievement_type}',
        'bug_achievement',
        bug.id,
    )
    return True


def award_submission_achievements(bug) -> None:
    award_currency(
        bug.owner,
        SUBMISSION_REWARD,
        'approved_bug_submission',
        'bug',
        bug.id,
    )
    award_achievement(
        bug,
        'first_submission',
        'Arena Arrival',
        '★',
        'Entered the BattleBugs arena.',
    )
    if bug.species_id:
        # Per-user unique species bonus
        existing_species_count = Bug.query.filter(
            Bug.user_id == bug.user_id,
            Bug.species_id == bug.species_id,
            Bug.id != bug.id,
        ).count()
        if existing_species_count == 0:
            award_currency(
                bug.owner,
                UNIQUE_SPECIES_REWARD,
                'unique_species_submission',
                'bug',
                bug.id,
            )
            award_achievement(
                bug,
                'species_discovery',
                'Cataloged Challenger',
                '◇',
                'Contributed to the species collection.',
            )

        # Global first-ever pioneer bonus (across all users)
        global_species_count = Bug.query.filter(
            Bug.species_id == bug.species_id,
            Bug.id != bug.id,
        ).count()
        if global_species_count == 0:
            award_currency(
                bug.owner,
                ACHIEVEMENT_REWARDS.get('species_pioneer', 50),
                'achievement:species_pioneer',
                'bug',
                bug.id,
            )
            award_achievement(
                bug,
                'species_pioneer',
                'World First!',
                '🌍',
                'First ever to bring this species into the arena.',
                rarity='rare',
            )


def award_battle_achievements(winner, loser=None) -> None:
    if not winner:
        return
    award_achievement(
        winner,
        'first_win',
        'First Victory',
        '🏅',
        'Won a first recorded battle.',
    )
    wins = winner.wins or 0
    if wins >= 3:
        award_achievement(
            winner,
            'three_wins',
            'Arena Regular',
            '🥉',
            'Reached three battle wins.',
            rarity='uncommon',
        )
    if wins >= 5:
        award_achievement(
            winner,
            'five_wins',
            'Proven Gladiator',
            '🥈',
            'Reached five battle wins.',
            rarity='rare',
        )
    if wins >= 10:
        award_achievement(
            winner,
            'ten_wins',
            'Decade of Dominance',
            '🥇',
            'Reached ten battle wins.',
            rarity='rare',
        )
        _retire_bug(winner)


def award_tournament_champion(bug) -> None:
    award_achievement(
        bug,
        'tournament_champion',
        'Tournament Champion',
        'T',
        'Won a tournament.',
        rarity='rare',
    )


def award_lore_participation(bug) -> None:
    award_achievement(
        bug,
        'lore_magnet',
        'Lore Magnet',
        '📖',
        'Inspired community lore.',
        rarity='uncommon',
    )


def _retire_bug(bug) -> None:
    if bug.is_retired:
        return
    bug.is_retired = True
    bug.retired_at = datetime.utcnow()
    db.session.add(bug)
    award_achievement(
        bug,
        'arena_legend',
        'Arena Legend',
        '🏆',
        'Retired with 10+ wins — a true champion.',
        rarity='rare',
    )
    award_currency(
        bug.owner,
        ACHIEVEMENT_REWARDS.get('arena_legend', 200),
        'achievement:arena_legend',
        'bug',
        bug.id,
    )
