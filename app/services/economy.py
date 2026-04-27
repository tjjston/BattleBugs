from app import db
from app.models import CurrencyTransaction, User as _User


STAT_REGENERATION_COST = 50

SUBMISSION_REWARD = 20
UNIQUE_SPECIES_REWARD = 40

ACHIEVEMENT_REWARDS = {
    'first_submission': 10,
    'species_discovery': 25,
    'species_pioneer': 50,
    'first_win': 15,
    'three_wins': 25,
    'five_wins': 50,
    'ten_wins': 100,
    'tournament_champion': 100,
    'lore_magnet': 10,
    'arena_legend': 200,
}


class InsufficientCurrencyError(ValueError):
    pass


def award_currency(user, amount: int, reason: str, reference_type: str = None, reference_id: int = None):
    if not user or amount <= 0:
        return None
    user.accolade_points = (user.accolade_points or 0) + amount
    transaction = CurrencyTransaction(
        user_id=user.id,
        amount=amount,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.session.add(user)
    db.session.add(transaction)
    return transaction


def spend_currency(user, amount: int, reason: str, reference_type: str = None, reference_id: int = None):
    if not user or amount <= 0:
        return None
    # Re-fetch with a row lock to prevent concurrent double-spend on PostgreSQL.
    # SQLite silently ignores FOR UPDATE, so tests are unaffected.
    locked = db.session.query(_User).filter_by(id=user.id).with_for_update().first()
    balance = locked.accolade_points or 0
    if balance < amount:
        raise InsufficientCurrencyError(f'Need {amount} Accolade Points; current balance is {balance}.')
    locked.accolade_points = balance - amount
    user.accolade_points = locked.accolade_points  # keep caller's reference in sync
    transaction = CurrencyTransaction(
        user_id=user.id,
        amount=-amount,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.session.add(transaction)
    return transaction


def should_charge_for_stat_regeneration(user, bug) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'role', 'USER') in ['MODERATOR', 'ADMIN', 'OWNER'] and user.id != bug.user_id:
        return False
    return user.id == bug.user_id
