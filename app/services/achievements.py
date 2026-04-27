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


def award_battle_achievements(winner, loser=None) -> None:
    if not winner:
        return
    award_achievement(
        winner,
        'first_win',
        'First Victory',
        'I',
        'Won a first recorded battle.',
    )
    if (winner.wins or 0) >= 3:
        award_achievement(
            winner,
            'three_wins',
            'Arena Regular',
            'III',
            'Reached three battle wins.',
            rarity='uncommon',
        )
    if (winner.wins or 0) >= 5:
        award_achievement(
            winner,
            'five_wins',
            'Proven Gladiator',
            'V',
            'Reached five battle wins.',
            rarity='rare',
        )


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
        'L',
        'Inspired community lore.',
        rarity='uncommon',
    )
