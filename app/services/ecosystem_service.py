"""
Ecosystem Map Service
Computes combat-type win-rate matrix and species relationship graph from battle history.
Results are cached in-process for 30 minutes.
"""
from __future__ import annotations

import time
from typing import Any

from app.services.battle_engine import MATCHUP_MATRIX

_cache: dict[str, Any] = {}
CACHE_TTL = 1800  # 30 minutes


# All known combat types (for consistent matrix axes)
ALL_ATTACK_TYPES = ['piercing', 'crushing', 'slashing', 'venom', 'chemical', 'grappling', 'sonic', 'electric', 'neutral']
ALL_DEFENSE_TYPES = ['hard_shell', 'segmented_armor', 'evasive', 'hairy_spiny', 'toxic_skin', 'thick_hide', 'unarmored', 'regenerative', 'bioluminescent']


def get_combat_type_matrix() -> dict[tuple, dict]:
    """Return a dict keyed by (attack_type, defense_type) with win stats from real battles."""
    from app.models import Battle

    battles = Battle.query.filter(Battle.winner_id.isnot(None)).all()
    matrix: dict[tuple, dict] = {}

    for battle in battles:
        b1, b2 = battle.bug1, battle.bug2
        if not b1 or not b2:
            continue

        pairs = []
        if b1.attack_type and b2.defense_type:
            pairs.append((b1.attack_type, b2.defense_type, battle.winner_id == b1.id))
        if b2.attack_type and b1.defense_type:
            pairs.append((b2.attack_type, b1.defense_type, battle.winner_id == b2.id))

        for atk, dfs, won in pairs:
            key = (atk.lower(), dfs.lower())
            if key not in matrix:
                matrix[key] = {'wins': 0, 'total': 0}
            matrix[key]['total'] += 1
            if won:
                matrix[key]['wins'] += 1

    return matrix


def build_matrix_table(live_matrix: dict[tuple, dict]) -> list[list]:
    """Return a 2-D list for rendering the matchup table.
    Each cell has: {'theoretical': float, 'win_rate': float|None, 'total': int}
    """
    rows = []
    for atk in ALL_ATTACK_TYPES:
        row = []
        for dfs in ALL_DEFENSE_TYPES:
            theoretical = MATCHUP_MATRIX.get(atk, {}).get(dfs, 1.0)
            key = (atk, dfs)
            live = live_matrix.get(key, {})
            total = live.get('total', 0)
            win_rate = (live['wins'] / total * 100) if total > 0 else None
            row.append({'theoretical': theoretical, 'win_rate': win_rate, 'total': total})
        rows.append(row)
    return rows


def get_species_graph() -> dict:
    """Return nodes + edges for a D3 species relationship graph from battle history."""
    from app.models import Battle

    battles = Battle.query.filter(Battle.winner_id.isnot(None)).all()
    species_map: dict[int, dict] = {}
    edges: dict[tuple, dict] = {}

    def _ensure_species(bug, sid):
        if sid not in species_map:
            si = bug.species_info
            name = (si.common_name or si.scientific_name) if si else f'#{sid}'
            species_map[sid] = {'id': sid, 'name': name, 'wins': 0, 'losses': 0}

    for battle in battles:
        b1, b2 = battle.bug1, battle.bug2
        if not b1 or not b2:
            continue
        s1, s2 = b1.species_id, b2.species_id
        if not s1 or not s2 or s1 == s2:
            continue

        _ensure_species(b1, s1)
        _ensure_species(b2, s2)

        if battle.winner_id == b1.id:
            species_map[s1]['wins'] += 1
            species_map[s2]['losses'] += 1
            predator, prey = s1, s2
        else:
            species_map[s2]['wins'] += 1
            species_map[s1]['losses'] += 1
            predator, prey = s2, s1

        edge_key = (min(s1, s2), max(s1, s2))
        if edge_key not in edges:
            edges[edge_key] = {'source': edge_key[0], 'target': edge_key[1], 'encounters': 0, 'first_wins': 0}
        edges[edge_key]['encounters'] += 1
        if predator == edge_key[0]:
            edges[edge_key]['first_wins'] += 1

    nodes = []
    for sp in species_map.values():
        total = sp['wins'] + sp['losses']
        sp['total'] = total
        sp['win_rate'] = round(sp['wins'] / total * 100, 1) if total else 0
        nodes.append(sp)

    links = []
    for e in edges.values():
        e['win_rate_source'] = round(e['first_wins'] / e['encounters'] * 100, 1) if e['encounters'] else 50
        links.append(e)

    return {'nodes': nodes, 'links': links}


def build_size_matrix_table() -> list[list]:
    """Return a 5×5 table of size advantage multipliers (attacker × defender)."""
    from app.services.battle_engine import SIZE_ORDER, SIZE_BASE_MODIFIER
    rows = []
    for attacker in SIZE_ORDER:
        row = []
        for defender in SIZE_ORDER:
            if attacker == defender:
                row.append(1.0)
            else:
                row.append(SIZE_BASE_MODIFIER.get((attacker, defender), 1.0))
        rows.append(row)
    return rows


def get_ecosystem_data() -> dict:
    """Cached ecosystem data (30-min TTL)."""
    now = time.time()
    if _cache.get('data') and (now - _cache.get('at', 0)) < CACHE_TTL:
        return _cache['data']

    live_matrix = get_combat_type_matrix()
    from app.services.battle_engine import SIZE_ORDER
    data = {
        'matrix_table': build_matrix_table(live_matrix),
        'attack_types': ALL_ATTACK_TYPES,
        'defense_types': ALL_DEFENSE_TYPES,
        'size_matrix': build_size_matrix_table(),
        'size_order': SIZE_ORDER,
        'species_graph': get_species_graph(),
        'has_battle_data': bool(live_matrix),
    }
    _cache['data'] = data
    _cache['at'] = now
    return data
