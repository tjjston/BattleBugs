from app import db
from app.models import Battle
from app.services.battle_engine import calculate_battle_stats, determine_winner_with_xfactor, simulate_battle
from tests.conftest import create_bug


def test_matchup_and_size_modifiers_are_visible(app, user):
    big = create_bug(user, nickname='Big', attack_type='crushing', defense_type='hard_shell', size_class='large')
    small = create_bug(user, nickname='Small', attack_type='venom', defense_type='thick_hide', size_class='tiny')

    stats = calculate_battle_stats(big, small)

    assert stats['bug1_modifier'] > 1
    assert stats['bug2_modifier'] >= 1
    assert stats['predicted_bug1_effective'] > stats['bug1_power']


def test_determine_winner_uses_visible_stats_with_xfactor(monkeypatch, user):
    stronger = create_bug(user, nickname='Strong', attack=20, defense=20, speed=20, xfactor=0)
    weaker = create_bug(user, nickname='Weak', attack=5, defense=5, speed=5, xfactor=5)
    monkeypatch.setattr('app.services.battle_engine.random.uniform', lambda _a, _b: 1.0)

    assert determine_winner_with_xfactor(stronger, weaker).id == stronger.id


def test_simulate_battle_awards_win_and_achievement(monkeypatch, user):
    winner = create_bug(user, nickname='Winner', attack=20, defense=20, speed=20, xfactor=0)
    loser = create_bug(user, nickname='Loser', attack=1, defense=1, speed=1, xfactor=0)
    monkeypatch.setattr('app.services.battle_engine.random.uniform', lambda _a, _b: 1.0)
    monkeypatch.setattr('app.services.battle_engine.generate_lore_enhanced_battle_narrative', lambda *_args: 'battle')

    battle = simulate_battle(winner, loser)

    assert db.session.get(Battle, battle.id).winner_id == winner.id
    assert winner.wins == 1
    assert loser.losses == 1
    assert winner.achievements.count() == 1
