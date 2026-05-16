"""
Special-ability catalog with balanced combat modifiers.

Every ability is a single, *slight* modifier on top of the base 6-stat
formula in ``battle_engine.determine_winner_with_xfactor``.

Magnitude guardrails (intentional ceilings — keep abilities flavor, not
match-deciders):
    stat_bonus    +3 to +6 on one stat
    power_mult    +2% to +4% on final power
    type_adv_amp  +10% to +20% to an existing type-advantage bonus
    type_disadv_dampen   +10% to +20% recovery toward 1.0 from disadvantage
    size_disadv_dampen   +10% to +20% recovery toward 1.0 from size deficit
    proc_dodge    8% to 12% chance to skip opponent's type advantage
    counter       4% to 8% reflected as bonus power vs hit attacker
    vs_attack_type   +2% to +5% power when opponent has that attack_type
    vs_defense_type  +2% to +5% power when opponent has that defense_type

The catalog is mapped by slug; bug.ability_slug stores the slug while
bug.special_ability keeps the display name (LLM-coined or catalog name).
The resolver picks the best slug for any free-form name using keyword
overlap, then falls back to attack_type / defense_type pairing.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Effect builders ─────────────────────────────────────────────────────

def _stat(stat: str, amount: int) -> dict:
    return {'kind': 'stat_bonus', 'stat': stat, 'amount': amount}

def _power(pct: float) -> dict:
    return {'kind': 'power_mult', 'pct': pct}

def _adv_amp(pct: float) -> dict:
    return {'kind': 'type_adv_amp', 'pct': pct}

def _disadv_dampen(pct: float) -> dict:
    return {'kind': 'type_disadv_dampen', 'pct': pct}

def _size_dampen(pct: float) -> dict:
    return {'kind': 'size_disadv_dampen', 'pct': pct}

def _dodge(pct: float) -> dict:
    return {'kind': 'proc_dodge', 'pct': pct}

def _counter(pct: float) -> dict:
    return {'kind': 'counter', 'pct': pct}

def _vs_atk(t: str, pct: float) -> dict:
    return {'kind': 'vs_attack_type', 'type': t, 'pct': pct}

def _vs_def(t: str, pct: float) -> dict:
    return {'kind': 'vs_defense_type', 'type': t, 'pct': pct}


@dataclass(frozen=True)
class Ability:
    slug: str
    name: str
    description: str
    effect: dict
    keywords: tuple = field(default=())
    suits_attack_type: tuple = field(default=())     # for fallback matching
    suits_defense_type: tuple = field(default=())


# ── Catalog ─────────────────────────────────────────────────────────────
#
# Organized by effect family for review/balance. Names are grounded in
# real entomology and arachnology vocabulary, with a few stylized variants
# so the LLM has plenty of synonyms to map onto.

_ABILITIES: list[Ability] = [
    # ── Mandible / strike family — +attack ──────────────────────────────
    Ability('mandible_vice',       'Mandible Vice',         'A locking bite that drives raw mandible force into the strike.', _stat('attack', 5), ('mandible', 'vice', 'bite', 'jaw'), ('crushing', 'piercing')),
    Ability('crushing_grip',       'Crushing Grip',         'Pincers clamp with bone-breaking pressure.',                       _stat('attack', 6), ('crush', 'crushing', 'grip', 'clamp'), ('crushing',)),
    Ability('rootsplitter_slam',   'Rootsplitter Slam',     'Body-weight slam that splits wood and exoskeletons alike.',        _stat('attack', 6), ('slam', 'root', 'split'), ('crushing',)),
    Ability('forceps_grab',        'Forceps Grab',          'Hooked forceps catch and hold while the head delivers the blow.',  _stat('attack', 4), ('forceps', 'grab', 'cerci'), ('piercing', 'grappling')),
    Ability('raptorial_ambush',    'Raptorial Ambush',      'Folded forelimbs unleash a single, devastating strike.',           _stat('attack', 6), ('raptorial', 'ambush', 'strike'), ('piercing', 'grappling')),
    Ability('antler_lock',         'Antler Lock',           'Branched mandibles interlock and wrench the opponent down.',       _stat('attack', 5), ('antler', 'mandible', 'lock'), ('grappling', 'crushing')),
    Ability('rostrum_strike',      'Rostrum Strike',        'A sharpened rostrum pierces between the plates.',                  _stat('attack', 5), ('rostrum', 'beak', 'pierce'), ('piercing',)),
    Ability('toe_biter_ambush',    'Toe-Biter Ambush',      'An underwater lunge with a piercing beak.',                        _stat('attack', 5), ('toe-biter', 'lethocerus', 'ambush'), ('piercing',)),
    Ability('mandible_lock',       'Mandible Lock',         'Once the jaws close, only release breaks the hold.',               _stat('attack', 4), ('mandible', 'lock'), ('grappling',)),
    Ability('barbed_hypostome',    'Barbed Hypostome',      'A backward-barbed feeding tube anchors and tears.',                _stat('attack', 4), ('hypostome', 'barbed', 'tick'), ('piercing',)),
    Ability('hooked_chelicerae',   'Hooked Chelicerae',     'Chelicerae catch the carapace edge before the fangs sink in.',    _stat('attack', 4), ('chelicerae', 'hook', 'fang'), ('piercing',)),
    Ability('strike_chain',        'Strike Chain',          'A rapid double-strike sequence overwhelms blocks.',                _stat('attack', 4), ('strike', 'chain', 'combo'), ('slashing',)),
    Ability('serrated_edge',       'Serrated Edge',         'Saw-toothed mandibles drag and tear.',                             _stat('attack', 5), ('serrated', 'saw', 'tear'), ('slashing',)),
    Ability('iron_jaw',            'Iron Jaw',              'Disproportionately thick mandibles for the bug\'s size.',          _stat('attack', 5), ('iron', 'jaw'), ('crushing',)),
    Ability('predator_clamp',      'Predator Clamp',        'A clamp tuned to crush the cervical joint.',                       _stat('attack', 4), ('predator', 'clamp'), ('crushing',)),
    Ability('killing_pinch',       'Killing Pinch',         'Pincer pressure tuned to a precise lethal point.',                 _stat('attack', 4), ('killing', 'pinch'), ('crushing',)),
    Ability('stalker_lunge',       'Stalker Lunge',         'A patient build-up explodes into a single committed strike.',      _stat('attack', 5), ('stalker', 'lunge'), ('piercing',)),
    Ability('skull_split',         'Skull Split',           'A wedge-shaped head meant for splitting carapace seams.',          _stat('attack', 5), ('skull', 'split', 'wedge'), ('crushing',)),
    Ability('axe_strike',          'Axe Strike',            'A cleaving downstroke with reinforced jaws.',                      _stat('attack', 5), ('axe', 'cleave'), ('slashing',)),
    Ability('hammer_blow',         'Hammer Blow',           'Body-mass swing built around a thickened head.',                   _stat('attack', 6), ('hammer', 'blow'), ('crushing',)),

    # ── Armor / shell family — +defense ────────────────────────────────
    Ability('armored_shell',       'Armored Shell',         'Reinforced chitin spreads incoming force across plates.',          _stat('defense', 6), ('armor', 'shell', 'chitin'), suits_defense_type=('hard_shell',)),
    Ability('elytra_plate',        'Elytra Plate',          'Hardened forewings double as a frontal shield.',                   _stat('defense', 5), ('elytra', 'plate', 'wing'), suits_defense_type=('hard_shell',)),
    Ability('segmented_plates',    'Segmented Plates',      'Articulated plates flex on impact instead of cracking.',           _stat('defense', 5), ('segment', 'plate'), suits_defense_type=('segmented_armor',)),
    Ability('iron_ball_form',      'Iron Ball Form',        'Body curls into a near-impenetrable sphere.',                      _stat('defense', 6), ('ball', 'curl', 'sphere'), suits_defense_type=('hard_shell', 'segmented_armor')),
    Ability('soil_anchor',         'Soil Anchor',           'Hooked tarsi anchor the bug, redistributing strike force.',        _stat('defense', 4), ('anchor', 'soil', 'tarsus'), suits_defense_type=('thick_hide',)),
    Ability('thorn_camouflage',    'Thorn Camouflage',      'Spines and a thorn-like profile deflect glancing blows.',          _stat('defense', 4), ('thorn', 'spine'), suits_defense_type=('hairy_spiny',)),
    Ability('bark_camouflage',     'Bark Camouflage',       'Bark-textured cuticle deflects attention and impact.',             _stat('defense', 4), ('bark', 'camouflage'), suits_defense_type=('evasive', 'hard_shell')),
    Ability('thick_cuticle',       'Thick Cuticle',         'A heavy cuticle layer absorbs blunt force.',                       _stat('defense', 5), ('cuticle', 'thick'), suits_defense_type=('thick_hide',)),
    Ability('reinforced_carapace', 'Reinforced Carapace',   'Cross-linked sclerites reinforce the dorsal carapace.',            _stat('defense', 5), ('carapace', 'reinforced'), suits_defense_type=('hard_shell',)),
    Ability('plate_lock',          'Plate Lock',            'Locking plates seal vulnerable seams under pressure.',             _stat('defense', 5), ('plate', 'lock', 'seam'), suits_defense_type=('segmented_armor',)),
    Ability('keel_chitin',         'Keel Chitin',           'A central ridge channels blows aside.',                            _stat('defense', 4), ('keel', 'ridge'), suits_defense_type=('hard_shell',)),
    Ability('bristle_wall',        'Bristle Wall',          'Dense setae form a damping barrier.',                              _stat('defense', 4), ('bristle', 'setae', 'hair'), suits_defense_type=('hairy_spiny',)),
    Ability('callused_hide',       'Callused Hide',         'Tough, callused integument shrugs off scrapes.',                   _stat('defense', 4), ('callus', 'hide'), suits_defense_type=('thick_hide',)),
    Ability('chitin_layering',     'Chitin Layering',       'Stacked chitin laminae diffuse penetrating blows.',                _stat('defense', 5), ('chitin', 'lamina'), suits_defense_type=('hard_shell',)),
    Ability('subelytral_pocket',   'Subelytral Pocket',     'A reinforced air pocket cushions impacts under the elytra.',       _stat('defense', 4), ('subelytral', 'pocket'), suits_defense_type=('hard_shell',)),
    Ability('rolling_defense',     'Rolling Defense',       'Rolls with the blow, bleeding off momentum.',                      _stat('defense', 4), ('roll', 'defense'), suits_defense_type=('evasive',)),
    Ability('chrysalis_calm',      'Chrysalis Calm',        'A still, braced posture transfers force to the ground.',           _stat('defense', 4), ('chrysalis', 'brace'), suits_defense_type=('hard_shell',)),
    Ability('stone_skin',          'Stone Skin',            'Mineralised integument behaves like rock under attack.',           _stat('defense', 6), ('stone', 'mineral'), suits_defense_type=('thick_hide',)),
    Ability('shell_lock',          'Shell Lock',            'Two halves of the shell seal flush along their hinge.',            _stat('defense', 5), ('shell', 'lock', 'hinge'), suits_defense_type=('hard_shell',)),
    Ability('rivet_plate',         'Rivet Plate',           'Rivet-like nodules pin the cuticle into a rigid lattice.',         _stat('defense', 5), ('rivet', 'plate'), suits_defense_type=('hard_shell',)),

    # ── Wings / speed family — +speed ──────────────────────────────────
    Ability('aerial_assault',      'Aerial Assault',        'Wings carry the bug above blocks and counterattacks.',             _stat('speed', 6), ('aerial', 'wing', 'flight'), ('piercing', 'slashing')),
    Ability('hovering_strike',     'Hovering Strike',       'Holds altitude to pick the moment of attack.',                     _stat('speed', 5), ('hover', 'wing'), ('piercing',)),
    Ability('quickwing',           'Quickwing',             'Fast wingbeat for sharp directional changes.',                     _stat('speed', 5), ('quickwing', 'wingbeat'), ('slashing',)),
    Ability('darting_flight',      'Darting Flight',        'Erratic, hard-to-track flight pattern.',                           _stat('speed', 5), ('dart', 'flight'), suits_defense_type=('evasive',)),
    Ability('haltere_balance',     'Haltere Balance',       'Gyroscopic halteres allow tight in-flight turns.',                 _stat('speed', 4), ('haltere', 'balance'), ('slashing',)),
    Ability('diving_assault',      'Diving Assault',        'Drops out of the air at terminal speed.',                          _stat('speed', 5), ('diving', 'dive'), ('piercing',)),
    Ability('leap_drop',           'Leap-Drop',             'A spring-loaded leap then a controlled descent.',                  _stat('speed', 4), ('leap', 'drop'), ('crushing',)),
    Ability('click_launch',        'Click Launch',          'A spring mechanism launches the body away from danger.',           _stat('speed', 5), ('click', 'launch'), suits_defense_type=('evasive',)),
    Ability('click_escape',        'Click Escape',          'A sudden mechanical click rolls the bug clear.',                   _dodge(0.10), ('click', 'escape'), suits_defense_type=('evasive',)),
    Ability('scatter_reflex',      'Scatter Reflex',        'A startle response that breaks line-of-attack.',                   _stat('speed', 4), ('scatter', 'reflex'), suits_defense_type=('evasive',)),
    Ability('leg_drop_escape',     'Leg-Drop Escape',       'Sheds a leg to break a grapple cleanly.',                          _dodge(0.10), ('leg', 'drop', 'autotomy'), suits_defense_type=('evasive',)),
    Ability('whip_legs',           'Whip Legs',             'Long legs whip in a wide arc that controls range.',                _stat('speed', 4), ('whip', 'leg'), ('slashing',)),
    Ability('leg_whip_barrage',    'Leg-Whip Barrage',      'A rapid series of leg strikes hides the real attack.',             _stat('speed', 5), ('leg', 'whip', 'barrage'), ('slashing',)),
    Ability('wind_runner',         'Wind Runner',           'Exploits air currents for sudden bursts.',                         _stat('speed', 4), ('wind', 'runner'), suits_defense_type=('evasive',)),
    Ability('skater_glide',        'Skater Glide',          'Surface-tension glide bypasses ground commitments.',               _stat('speed', 4), ('skater', 'glide'), suits_defense_type=('evasive',)),
    Ability('cricket_kick',        'Cricket Kick',          'Spring-loaded hind legs add range and recoil.',                    _stat('speed', 4), ('cricket', 'kick'), ('crushing',)),
    Ability('grasshopper_arc',     'Grasshopper Arc',       'A long jumping arc dictates engagement distance.',                 _stat('speed', 5), ('grasshopper', 'arc'), ('slashing',)),
    Ability('quickstep',           'Quickstep',             'Tight, low strides under the opponent\'s blow.',                   _stat('speed', 4), ('quickstep', 'step'), suits_defense_type=('evasive',)),
    Ability('wing_buzz',           'Wing Buzz',             'A constant buzz that masks footwork.',                             _stat('speed', 3), ('wing', 'buzz'), ('sonic',)),
    Ability('halt_pivot',          'Halt-Pivot',            'A sudden full-stop pivot wrong-foots the attacker.',               _stat('speed', 4), ('halt', 'pivot'), suits_defense_type=('evasive',)),

    # ── Venom / chemical — +lethality, type-adv amp ────────────────────
    Ability('venomous_strike',     'Venomous Strike',       'Hemotoxic injection on bite contact.',                             _stat('lethality', 8), ('venom', 'venomous', 'fang', 'neurotoxin', 'toxin'), ('venom',)),
    Ability('neurotoxic_bite',     'Neurotoxic Bite',       'Neurotoxin disrupts opponent muscle coordination.',                _adv_amp(0.18), ('neurotoxin', 'venom', 'bite'), ('venom',)),
    Ability('hemotoxic_fang',      'Hemotoxic Fang',        'Cytotoxin softens tissue ahead of the bite.',                      _stat('lethality', 7), ('hemotoxic', 'fang', 'cytotoxin'), ('venom',)),
    Ability('paralytic_inject',    'Paralytic Inject',      'Slow-onset paralytic shuts down counter-strikes.',                 _adv_amp(0.15), ('paralytic', 'paralysis'), ('venom',)),
    Ability('acid_spit',           'Acid Spit',             'A ranged caustic spray that bypasses armor seams.',                _adv_amp(0.18), ('acid', 'spit', 'spray'), ('chemical',)),
    Ability('boiling_acid_blast',  'Boiling Acid Blast',    'Superheated defensive spray scalds attackers.',                    _adv_amp(0.20), ('acid', 'blast', 'bombardier'), ('chemical',)),
    Ability('aldehyde_cloud',      'Aldehyde Cloud',        'Aldehyde mist disorients and burns mucosa.',                       _stat('lethality', 6), ('aldehyde', 'cloud'), ('chemical',)),
    Ability('formic_arc',          'Formic Arc',            'Formic acid arc lands on the eyes and joints.',                    _adv_amp(0.15), ('formic', 'acid', 'ant'), ('chemical',)),
    Ability('stench_shield',       'Stench Shield',         'A foul defensive scent ruins committed attackers.',                _counter(0.06), ('stench', 'scent'), suits_defense_type=('toxic_skin',)),
    Ability('quinone_spray',       'Quinone Spray',         'Burst of quinones at the attack window.',                          _adv_amp(0.18), ('quinone', 'spray'), ('chemical',)),
    Ability('cyanide_warning',     'Cyanide Warning',       'Hydrogen cyanide emission deters follow-through.',                 _stat('lethality', 6), ('cyanide', 'cyanogen'), ('chemical',)),
    Ability('toxin_breath',        'Toxin Breath',          'Exhaled volatile toxins on close engagement.',                     _adv_amp(0.12), ('toxin', 'breath'), ('chemical',)),
    Ability('urticating_hairs',    'Urticating Hairs',      'Detachable hairs lodge in soft tissue and itch.',                  _counter(0.08), ('urticating', 'hair', 'setae'), suits_defense_type=('hairy_spiny',)),
    Ability('toxic_bristle',       'Toxic Bristle',         'Bristles laced with chemical irritant.',                           _counter(0.07), ('toxic', 'bristle', 'caterpillar'), suits_defense_type=('hairy_spiny',)),
    Ability('bombardier_burst',    'Bombardier Burst',      'A directional chemical detonation in the attack pocket.',          _adv_amp(0.20), ('bombardier', 'burst'), ('chemical',)),
    Ability('venom_sting',         'Venom Sting',           'A precise stinger drop targets gaps.',                             _stat('lethality', 7), ('sting', 'venom'), ('venom',)),
    Ability('lethal_dose',         'Lethal Dose',           'A larger-than-usual venom payload per strike.',                    _adv_amp(0.20), ('lethal', 'dose', 'venom'), ('venom',)),
    Ability('cytotoxic_smear',     'Cytotoxic Smear',       'Skin-contact cytotoxin from glandular tarsi.',                     _stat('lethality', 6), ('cytotoxic', 'smear'), ('chemical', 'venom')),
    Ability('soporific_bite',      'Soporific Bite',        'Sedating bite slows opponent reactions.',                          _adv_amp(0.12), ('soporific', 'sedating', 'bite'), ('venom',)),
    Ability('alkaloid_drip',       'Alkaloid Drip',         'Alkaloid-laden secretions on the strike surface.',                 _stat('lethality', 5), ('alkaloid', 'drip'), ('chemical',)),

    # ── Camouflage / cunning — type disadvantage dampen ────────────────
    Ability('mirror_shield',       'Mirror Shield',         'Reflective patterning misleads the strike vector.',                _disadv_dampen(0.18), ('mirror', 'reflect'), suits_defense_type=('evasive',)),
    Ability('cryptic_pose',        'Cryptic Pose',          'Holds a profile that breaks predator search image.',               _disadv_dampen(0.15), ('cryptic', 'pose'), suits_defense_type=('evasive',)),
    Ability('twig_mimic',          'Twig Mimic',            'Indistinguishable from a twig until the strike fails.',            _disadv_dampen(0.20), ('twig', 'mimic'), suits_defense_type=('evasive',)),
    Ability('leaf_drift',          'Leaf Drift',            'A wind-swayed posture confuses tracking.',                         _disadv_dampen(0.15), ('leaf', 'drift'), suits_defense_type=('evasive',)),
    Ability('lichen_blend',        'Lichen Blend',          'Lichen-pattern body breaks outline against bark.',                 _disadv_dampen(0.15), ('lichen', 'blend'), suits_defense_type=('evasive',)),
    Ability('ant_mimicry',         'Ant Mimicry',           'Posture and gait copy an ant to deter committed attacks.',         _disadv_dampen(0.15), ('ant', 'mimic'), suits_defense_type=('evasive',)),
    Ability('wasp_mimicry',        'Wasp Mimicry',          'Wasp-like banding triggers caution in the opponent.',              _disadv_dampen(0.18), ('wasp', 'mimic'), suits_defense_type=('evasive',)),
    Ability('beetle_disguise',     'Beetle Disguise',       'Coloration mimics a stiffer, harder species.',                     _disadv_dampen(0.12), ('beetle', 'disguise'), suits_defense_type=('evasive',)),
    Ability('shadow_drape',        'Shadow Drape',          'Holds in deep shadow during the swing.',                           _disadv_dampen(0.15), ('shadow', 'drape'), suits_defense_type=('evasive',)),
    Ability('twilight_glide',      'Twilight Glide',        'Low-light maneuver windows where vision is weakest.',              _disadv_dampen(0.15), ('twilight', 'glide'), suits_defense_type=('evasive',)),
    Ability('dust_veil',           'Dust Veil',             'A puff of dust on engagement obscures the read.',                  _disadv_dampen(0.15), ('dust', 'veil'), suits_defense_type=('evasive',)),
    Ability('powder_veil',         'Powder Veil',           'Detachable wing-scale powder masks the body.',                     _disadv_dampen(0.18), ('powder', 'veil', 'scale'), suits_defense_type=('evasive',)),
    Ability('disorienting_flash',  'Disorienting Flash',    'A sudden flash of color breaks visual lock.',                      _disadv_dampen(0.15), ('disorient', 'flash'), suits_defense_type=('evasive',)),
    Ability('eyespot_bluff',       'Eyespot Bluff',         'False eyespots redirect the attack.',                              _disadv_dampen(0.12), ('eyespot', 'bluff'), suits_defense_type=('evasive',)),
    Ability('false_head',          'False Head',            'A decoy head soaks the opponent\'s first commitment.',             _disadv_dampen(0.15), ('false', 'head', 'decoy'), suits_defense_type=('evasive',)),
    Ability('split_silhouette',    'Split Silhouette',      'Body banding fractures the visual outline.',                       _disadv_dampen(0.12), ('split', 'silhouette'), suits_defense_type=('evasive',)),
    Ability('nocturnal_ambush',    'Nocturnal Ambush',      'Strikes after sundown when vision is poor.',                       _disadv_dampen(0.18), ('nocturnal', 'ambush'), suits_defense_type=('evasive',)),
    Ability('canopy_shadow',       'Canopy Shadow',         'Uses canopy dapple to flicker in and out of sight.',               _disadv_dampen(0.12), ('canopy', 'shadow'), suits_defense_type=('evasive',)),
    Ability('soil_blend',          'Soil Blend',            'Body color matches the soil substrate.',                           _disadv_dampen(0.12), ('soil', 'blend'), suits_defense_type=('evasive',)),
    Ability('moss_drape',          'Moss Drape',            'Carries fragments of moss across the cuticle.',                    _disadv_dampen(0.12), ('moss', 'drape'), suits_defense_type=('evasive',)),

    # ── Grip / grappling — +grip ───────────────────────────────────────
    Ability('web_trap',            'Web Trap',              'Anchored silk webbing limits opponent footing.',                   _stat('grip', 8), ('web', 'silk', 'trap'), ('grappling',)),
    Ability('web_wrap',            'Web Wrap',              'Restraint webbing wraps limbs faster than they pull.',             _stat('grip', 8), ('web', 'wrap'), ('grappling',)),
    Ability('silk_snare',          'Silk Snare',            'Tripline silk catches a limb at the worst moment.',                _stat('grip', 7), ('silk', 'snare'), ('grappling',)),
    Ability('book_scorpion_grip',  'Book-Scorpion Grip',    'Pincers anchored against a fold of cuticle.',                      _stat('grip', 7), ('book-scorpion', 'pseudoscorpion', 'grip'), ('grappling',)),
    Ability('claw_anchor',         'Claw Anchor',           'Tarsal claws anchor on rough cuticle to control range.',           _stat('grip', 6), ('claw', 'anchor'), ('grappling',)),
    Ability('tarsal_hook',         'Tarsal Hook',           'A single hook latches onto a sclerite seam.',                      _stat('grip', 5), ('tarsal', 'hook'), ('grappling',)),
    Ability('adhesive_pad',        'Adhesive Pad',          'Sticky tarsal pads make breakaway costly.',                        _stat('grip', 6), ('adhesive', 'pad'), ('grappling',)),
    Ability('barbed_pretarsus',    'Barbed Pretarsus',      'Backward barbs lock once engaged.',                                _stat('grip', 7), ('barbed', 'pretarsus'), ('grappling',)),
    Ability('foreleg_clamp',       'Foreleg Clamp',         'Forelegs clamp the opponent\'s thorax.',                           _stat('grip', 6), ('foreleg', 'clamp'), ('grappling',)),
    Ability('spider_silk_bind',    'Spider-Silk Bind',      'Strong silk wraps the centre of mass.',                            _stat('grip', 7), ('silk', 'bind', 'spider'), ('grappling',)),
    Ability('mantis_pin',          'Mantis Pin',            'Spined forelegs pin the opponent in place.',                       _stat('grip', 6), ('mantis', 'pin'), ('grappling',)),
    Ability('crab_walk_pin',       'Crab-Walk Pin',         'A sideways approach denies escape angles.',                        _stat('grip', 5), ('crab', 'walk', 'pin'), ('grappling',)),
    Ability('scorpion_pedipalp',   'Scorpion Pedipalp',     'Pedipalps clamp and hold for the sting setup.',                    _stat('grip', 6), ('pedipalp', 'scorpion'), ('grappling',)),
    Ability('locking_femora',      'Locking Femora',        'Femur ridges interlock on contact.',                               _stat('grip', 6), ('femora', 'femur', 'lock'), ('grappling',)),
    Ability('vise_grasp',          'Vise Grasp',            'A locked grip that resists wriggling escape.',                     _stat('grip', 7), ('vise', 'grasp'), ('grappling',)),
    Ability('mucus_anchor',        'Mucus Anchor',          'Mucus secreted at the contact point glues briefly.',               _stat('grip', 5), ('mucus', 'anchor'), ('grappling',)),
    Ability('hairy_pad_seal',      'Hairy Pad Seal',        'Microscopic hairs on the pad multiply contact area.',              _stat('grip', 5), ('hairy', 'pad'), ('grappling',)),
    Ability('limb_twist',          'Limb Twist',            'A controlling twist disrupts opponent stance.',                    _stat('grip', 5), ('limb', 'twist'), ('grappling',)),
    Ability('suction_step',        'Suction Step',          'Suction-cup tarsi cling and slow disengagement.',                  _stat('grip', 5), ('suction', 'step'), ('grappling',)),
    Ability('crampon_grip',        'Crampon Grip',          'Spiked footing holds across vertical surfaces.',                   _stat('grip', 5), ('crampon', 'grip'), ('grappling',)),

    # ── Cunning / sensory — +cunning, type-disadvantage dampen ─────────
    Ability('antennal_read',       'Antennal Read',         'Reads vibrational tells before the opponent commits.',             _stat('cunning', 6), ('antenna', 'antennal'), ('sonic',)),
    Ability('survival_instinct',   'Survival Instinct',     'Withdraws from disadvantage instead of escalating.',               _disadv_dampen(0.15), ('survival', 'instinct'), suits_defense_type=('evasive',)),
    Ability('feint_step',          'Feint Step',            'A small bait step opens a clean line.',                            _stat('cunning', 5), ('feint', 'step'), suits_defense_type=('evasive',)),
    Ability('compound_vision',     'Compound Vision',       'Wide-angle ommatidia track multi-axis attacks.',                   _stat('cunning', 5), ('compound', 'vision', 'ommatidia'), suits_defense_type=('evasive',)),
    Ability('hunter_patience',     'Hunter Patience',       'Waits past the first attack window for a better one.',             _stat('cunning', 5), ('hunter', 'patience'), suits_defense_type=('evasive',)),
    Ability('vibration_sense',     'Vibration Sense',       'Detects approach through substrate vibration.',                    _stat('cunning', 5), ('vibration', 'tremor'), ('sonic',)),
    Ability('chemosense',          'Chemosense',            'Reads opponent chemistry in advance of contact.',                  _stat('cunning', 4), ('chemosense', 'palp'), suits_defense_type=('evasive',)),
    Ability('terrain_use',         'Terrain Use',           'Routes the fight through awkward terrain.',                        _stat('cunning', 5), ('terrain', 'route'), suits_defense_type=('evasive',)),
    Ability('strike_timing',       'Strike Timing',         'Locks onto opponent recovery frames.',                             _stat('cunning', 5), ('timing', 'strike'), suits_defense_type=('evasive',)),
    Ability('rear_eye_alert',      'Rear-Eye Alert',        'Rear-facing ocelli prevent flanking.',                             _stat('cunning', 4), ('ocelli', 'rear', 'eye'), suits_defense_type=('evasive',)),
    Ability('mimic_distress',      'Mimic Distress',        'Plays wounded to draw the attacker into a trap.',                  _stat('cunning', 5), ('mimic', 'distress'), suits_defense_type=('evasive',)),
    Ability('herd_predict',        'Herd Predict',          'Anticipates an opponent\'s next strike from prior patterns.',      _stat('cunning', 5), ('predict', 'herd'), suits_defense_type=('evasive',)),
    Ability('counter_read',        'Counter-Read',          'Reads the punch before it lands.',                                 _disadv_dampen(0.18), ('counter', 'read'), suits_defense_type=('evasive',)),
    Ability('cool_under_strike',   'Cool Under Strike',     'Avoids panic reactions that compound damage.',                     _disadv_dampen(0.12), ('cool', 'calm'), suits_defense_type=('evasive',)),
    Ability('focused_aim',         'Focused Aim',           'Picks a vulnerable joint instead of mass-area.',                   _stat('cunning', 4), ('aim', 'focus'), suits_defense_type=('evasive',)),
    Ability('quick_pivot',         'Quick Pivot',           'Rotates to keep the strong side toward the threat.',               _stat('cunning', 4), ('pivot', 'rotate'), suits_defense_type=('evasive',)),
    Ability('precision_targeting', 'Precision Targeting',   'Punishes the smallest opening with disproportionate force.',       _power(0.03), ('precision', 'target'), suits_defense_type=('evasive',)),
    Ability('predator_calm',       'Predator Calm',         'Refuses to escalate, banking energy for the kill.',                _disadv_dampen(0.15), ('predator', 'calm'), suits_defense_type=('evasive',)),
    Ability('scout_route',         'Scout Route',           'Picks the engagement spot in advance.',                            _stat('cunning', 4), ('scout', 'route'), suits_defense_type=('evasive',)),
    Ability('reroute_strike',      'Reroute Strike',        'Bends the strike around the obvious block.',                       _stat('cunning', 4), ('reroute', 'strike'), suits_defense_type=('evasive',)),

    # ── Sonic family — sonic attack amps ───────────────────────────────
    Ability('resonance_chirp',     'Resonance Chirp',       'Tuned stridulation rattles soft tissue.',                          _adv_amp(0.18), ('chirp', 'stridulation'), ('sonic',)),
    Ability('cicada_blast',        'Cicada Blast',          'High-amplitude tymbal blast at close range.',                      _adv_amp(0.20), ('cicada', 'tymbal'), ('sonic',)),
    Ability('cricket_song',        'Cricket Song',          'Rhythmic chirp masks footwork and lines up the strike.',           _power(0.03), ('cricket', 'song'), ('sonic',)),
    Ability('katydid_clatter',     'Katydid Clatter',       'Rapid file-and-scraper noise disrupts coordination.',              _adv_amp(0.15), ('katydid', 'clatter'), ('sonic',)),
    Ability('drumming_strike',     'Drumming Strike',       'Vibration through substrate amplifies impact perception.',         _power(0.03), ('drum', 'thump'), ('sonic',)),
    Ability('hawk_moth_buzz',      'Hawk-Moth Buzz',        'Low-frequency wingbeat saturates opponent hearing.',               _adv_amp(0.12), ('hawk', 'moth', 'buzz'), ('sonic',)),
    Ability('sonic_pulse',         'Sonic Pulse',           'A directed pulse of biological ultrasound.',                       _adv_amp(0.18), ('sonic', 'pulse'), ('sonic',)),
    Ability('vibration_strike',    'Vibration Strike',      'Strike timed to a vibration peak that travels.',                   _power(0.04), ('vibration', 'strike'), ('sonic',)),

    # ── Electric / exotic — type-adv amps + situational ────────────────
    Ability('static_discharge',    'Static Discharge',      'A faint cuticle discharge on grapple contact.',                    _adv_amp(0.20), ('static', 'discharge'), ('electric',)),
    Ability('bio_arc',             'Bio-Arc',               'Charges across moisture-rich contact zones.',                      _adv_amp(0.18), ('arc', 'bio'), ('electric',)),
    Ability('spark_jolt',          'Spark Jolt',            'A tiny jolt at the contact moment of the strike.',                 _adv_amp(0.15), ('spark', 'jolt'), ('electric',)),
    Ability('bioluminescent_blip', 'Bioluminescent Blip',   'A timed pulse blinds aimed attacks for a beat.',                   _dodge(0.10), ('bioluminescent', 'blip'), suits_defense_type=('bioluminescent',)),
    Ability('fireflies_flicker',   'Fireflies Flicker',     'Light pulses break visual lock at the strike.',                    _dodge(0.10), ('firefly', 'flicker'), suits_defense_type=('bioluminescent',)),

    # ── Display / intimidation — power_mult, conditional bonuses ───────
    Ability('warning_aposematism', 'Warning Aposematism',   'Bright warning patterns make committed attacks rarer.',            _power(0.03), ('warning', 'aposematism'), suits_defense_type=('toxic_skin',)),
    Ability('red_stain_threat',    'Red-Stain Threat',      'A flash of red signals chemical risk.',                            _power(0.03), ('red', 'stain', 'threat'), suits_defense_type=('toxic_skin',)),
    Ability('devil_coach_display', "Devil's-Coach-Horse Display", 'Threat display arches the body and bares the jaws.',           _stat('cunning', 4), ('devil', 'coach', 'display'), suits_defense_type=('toxic_skin',)),
    Ability('hissing_display',     'Hissing Display',       'Air-driven hiss intimidates inexperienced attackers.',             _power(0.03), ('hiss', 'display'), ('sonic',)),
    Ability('rear_up',             'Rear-Up',               'Rises onto rear legs to look larger.',                             _power(0.02), ('rear-up', 'rise'), suits_defense_type=('thick_hide',)),
    Ability('snake_mimic_pose',    'Snake Mimic Pose',      'Stretches to mimic a snake silhouette.',                           _power(0.03), ('snake', 'mimic', 'pose'),),
    Ability('false_strike_bluff',  'False-Strike Bluff',    'A bluff strike makes the opponent commit early.',                  _stat('cunning', 5), ('false', 'strike', 'bluff'), suits_defense_type=('evasive',)),
    Ability('flashing_threat',     'Flashing Threat',       'Color flash on the dorsum gives a beat of hesitation.',            _disadv_dampen(0.12), ('flash', 'threat'), suits_defense_type=('evasive',)),

    # ── Size-leverage — size disadvantage dampen, vs big/small ─────────
    Ability('giant_killer',        'Giant Killer',          'Tactics tuned to fight larger opponents.',                         _size_dampen(0.20), ('giant', 'killer'),),
    Ability('low_stance',          'Low Stance',            'A low body line denies size advantage.',                           _size_dampen(0.15), ('low', 'stance'),),
    Ability('weight_redirect',     'Weight Redirect',       'Channels heavier opponents into their own momentum.',              _size_dampen(0.18), ('weight', 'redirect'),),
    Ability('joint_attack',        'Joint Attack',          'Aims at limb joints to bypass mass.',                              _size_dampen(0.12), ('joint', 'attack'),),
    Ability('crawl_under',         'Crawl Under',           'Slips under the strike arc of larger opponents.',                  _size_dampen(0.15), ('crawl', 'under'),),
    Ability('small_target',        'Small Target',          'Presents a profile too small to hit cleanly.',                     _size_dampen(0.15), ('small', 'target'),),
    Ability('lever_grip',          'Lever Grip',            'Uses leverage points to control bigger limbs.',                    _size_dampen(0.18), ('lever', 'grip'),),
    Ability('underbody_strike',    'Underbody Strike',      'Strikes the unarmored underbelly of larger bugs.',                 _vs_def('thick_hide', 0.04), ('underbody', 'belly'),),

    # ── Anti-typing — vs_attack_type / vs_defense_type situational ─────
    Ability('venom_resistance',    'Venom Resistance',      'Hemolymph chemistry mutes injected toxins.',                       _vs_atk('venom', 0.05), ('venom', 'resistant'), suits_defense_type=('toxic_skin',)),
    Ability('chemical_shrug',      'Chemical Shrug',        'Cuticle resists chemical sprays.',                                 _vs_atk('chemical', 0.05), ('chemical', 'shrug'), suits_defense_type=('toxic_skin',)),
    Ability('piercing_guard',      'Piercing Guard',        'Plate seams aligned against piercing strikes.',                    _vs_atk('piercing', 0.04), ('piercing', 'guard'), suits_defense_type=('hard_shell',)),
    Ability('crush_brace',         'Crush Brace',           'Strong dorsal arch braces against crushing force.',                _vs_atk('crushing', 0.04), ('crush', 'brace'), suits_defense_type=('hard_shell',)),
    Ability('slash_deflect',       'Slash Deflect',         'Angled wing-cases deflect slashing arcs.',                         _vs_atk('slashing', 0.04), ('slash', 'deflect'), suits_defense_type=('hard_shell',)),
    Ability('grapple_break',       'Grapple Break',         'Tarsal claws and lubricant resist sustained grapples.',            _vs_atk('grappling', 0.04), ('grapple', 'break'), suits_defense_type=('evasive',)),
    Ability('sonic_dampen',        'Sonic Dampen',          'Tympanal membrane structure muffles incoming vibration.',          _vs_atk('sonic', 0.04), ('sonic', 'dampen'), suits_defense_type=('thick_hide',)),
    Ability('shell_cracker',       'Shell Cracker',         'Strike profile picks the lamina edge.',                            _vs_def('hard_shell', 0.04), ('shell', 'cracker'),),
    Ability('seam_strike',         'Seam Strike',           'Targets the gaps between segmented plates.',                       _vs_def('segmented_armor', 0.04), ('seam', 'strike'),),
    Ability('hair_clear',          'Hair Clear',            'Mandible sweep clears defensive setae before striking.',           _vs_def('hairy_spiny', 0.04), ('hair', 'clear'),),
    Ability('toxin_immune',        'Toxin Immune',          'Resists toxic-skin counter-irritants.',                            _vs_def('toxic_skin', 0.04), ('toxin', 'immune'),),
    Ability('hide_pierce',         'Hide Pierce',           'Designed to pierce thick hides.',                                  _vs_def('thick_hide', 0.04), ('hide', 'pierce'),),
    Ability('soft_target',         'Soft Target',           'Exploits unarmored bodies for clean strikes.',                     _vs_def('unarmored', 0.04), ('soft', 'target'),),
    Ability('regen_disruptor',     'Regen Disruptor',       'Wound chemistry that prevents quick closure.',                     _vs_def('regenerative', 0.04), ('regen', 'disruptor'),),
    Ability('flash_immune',        'Flash Immune',          'Compound vision unaffected by bioluminescent disruption.',          _vs_def('bioluminescent', 0.04), ('flash', 'immune'),),

    # ── Counter / proc family — counter and dodge procs ────────────────
    Ability('counter_pinch',       'Counter-Pinch',         'A reflexive pinch on grapple contact.',                            _counter(0.06), ('counter', 'pinch'), suits_defense_type=('evasive',)),
    Ability('reflex_strike',       'Reflex Strike',         'Snap-strike on incoming contact.',                                 _counter(0.07), ('reflex', 'strike'), suits_defense_type=('evasive',)),
    Ability('boomerang_kick',      'Boomerang Kick',        'A leg kick that returns to a guard position.',                     _counter(0.06), ('boomerang', 'kick'), suits_defense_type=('evasive',)),
    Ability('spine_counter',       'Spine Counter',         'Body spines puncture an attacker that commits.',                   _counter(0.08), ('spine', 'counter'), suits_defense_type=('hairy_spiny',)),
    Ability('barb_back',           'Barb-Back',             'Barbs along the dorsum punish over-commitment.',                   _counter(0.07), ('barb', 'back'), suits_defense_type=('hairy_spiny',)),
    Ability('thorn_riposte',       'Thorn Riposte',         'Stiff cuticular thorns press into attacker on contact.',           _counter(0.06), ('thorn', 'riposte'), suits_defense_type=('hairy_spiny',)),
    Ability('autotomy_reset',      'Autotomy Reset',        'Drops a non-essential limb to break the engagement.',              _dodge(0.10), ('autotomy', 'reset'), suits_defense_type=('evasive',)),
    Ability('death_feign',         'Death Feign',           'Plays dead to escape the kill stroke.',                            _dodge(0.10), ('death', 'feign', 'thanatosis'), suits_defense_type=('evasive',)),
    Ability('jump_dodge',          'Jump Dodge',            'Spring-loaded escape from the contact zone.',                      _dodge(0.10), ('jump', 'dodge'), suits_defense_type=('evasive',)),
    Ability('side_step',           'Side Step',             'A lateral half-step out of the strike line.',                      _dodge(0.08), ('side', 'step'), suits_defense_type=('evasive',)),
    Ability('mid_air_correct',     'Mid-Air Correct',       'In-flight correction breaks lock-on attacks.',                     _dodge(0.10), ('correct', 'wing'), suits_defense_type=('evasive',)),
    Ability('twitch_reflex',       'Twitch Reflex',         'A micro-twitch defeats the initial strike vector.',                _dodge(0.08), ('twitch', 'reflex'), suits_defense_type=('evasive',)),
    Ability('startle_recoil',      'Startle Recoil',        'Sudden recoil moves the body just past the strike.',               _dodge(0.08), ('startle', 'recoil'), suits_defense_type=('evasive',)),
    Ability('shadow_step',         'Shadow Step',           'Steps into shadow on a committed swing.',                          _dodge(0.10), ('shadow', 'step'), suits_defense_type=('evasive',)),
    Ability('barbed_counter',      'Barbed Counter',        'Counter-strike with a barbed limb.',                               _counter(0.07), ('barbed', 'counter'), suits_defense_type=('hairy_spiny',)),
    Ability('paddle_smack',        'Paddle Smack',          'A leg paddle redirects the attacker into a wall.',                 _counter(0.05), ('paddle', 'smack'), suits_defense_type=('evasive',)),
    Ability('whip_riposte',        'Whip Riposte',          'A whipping tail/limb returns on opponent over-commit.',            _counter(0.06), ('whip', 'riposte'), suits_defense_type=('evasive',)),
    Ability('grasping_counter',    'Grasping Counter',      'Grabs the strike-arm and pulls the attacker off balance.',         _counter(0.06), ('grasp', 'counter'), suits_defense_type=('evasive',)),

    # ── Regeneration / resilience — defense + counter ──────────────────
    Ability('rapid_clot',          'Rapid Clot',            'Hemolymph clots quickly under stress.',                            _stat('defense', 4), ('clot', 'hemolymph'), suits_defense_type=('regenerative',)),
    Ability('exoskeleton_self_seal','Exoskeleton Self-Seal','Cuticle seals minor cracks during the fight.',                     _stat('defense', 5), ('seal', 'exoskeleton'), suits_defense_type=('regenerative',)),
    Ability('mid_battle_molt',     'Mid-Battle Molt',       'A partial molt sheds damaged exoskeleton layers.',                 _stat('defense', 5), ('molt', 'midbattle'), suits_defense_type=('regenerative',)),
    Ability('limb_regrow',         'Limb Regrow',           'Capable of recovering a limb mid-fight (slowly).',                 _stat('defense', 4), ('regrow', 'regeneration'), suits_defense_type=('regenerative',)),
    Ability('hemolymph_pressure',  'Hemolymph Pressure',    'Pumps hemolymph to stiffen damaged areas.',                        _stat('defense', 4), ('hemolymph', 'pressure'), suits_defense_type=('thick_hide',)),
    Ability('tough_lining',        'Tough Lining',          'Internal lining resists internal damage.',                         _stat('defense', 4), ('tough', 'lining'),),

    # ── Colony / social — slight power_mult ────────────────────────────
    Ability('colony_swarm',        'Colony Swarm',          'Pheromonal recall summons swarm support cues.',                    _power(0.03), ('colony', 'swarm', 'pheromone'),),
    Ability('alarm_pheromone',     'Alarm Pheromone',       'Stress chemistry triggers a measured panic in attackers.',         _power(0.03), ('alarm', 'pheromone'),),
    Ability('trail_marker',        'Trail Marker',          'Chemical trail keeps it from re-engaging at a bad angle.',         _stat('cunning', 4), ('trail', 'marker'),),
    Ability('queen_signal',        'Queen Signal',          'Locks into a high-priority social cue.',                           _power(0.02), ('queen', 'signal'),),
    Ability('forager_focus',       'Forager Focus',         'Single-purpose target lock from foraging behavior.',               _stat('cunning', 4), ('forager', 'focus'),),

    # ── Water / niche ──────────────────────────────────────────────────
    Ability('submerge_ambush',     'Submerge Ambush',       'Holds breath beneath the surface for the strike.',                 _stat('cunning', 5), ('submerge', 'water'),),
    Ability('water_walk',          'Water Walk',            'Surface tension allows controlled approach.',                      _stat('speed', 4), ('water', 'walk'),),
    Ability('plastron_breath',     'Plastron Breath',       'Plastron of air keeps cuticle dry under attack.',                  _stat('defense', 4), ('plastron', 'water'),),
    Ability('current_drift',       'Current Drift',         'Drifts on the current to set up the strike.',                      _stat('speed', 4), ('current', 'drift'),),

    # ── Misc oddities (each unique but slight) ─────────────────────────
    Ability('bivalve_snap',        'Bivalve Snap',          'A single committed snap of the body for a high-impact strike.',    _power(0.04), ('bivalve', 'snap'),),
    Ability('book_lungs_holdout',  'Book-Lungs Holdout',    'Greater endurance keeps power steady late in the fight.',          _power(0.03), ('book', 'lung', 'spiracle'),),
    Ability('root_spike',          'Root Spike',            'A driven spike pinned to a buried root.',                          _stat('attack', 4), ('root', 'spike'), ('piercing',)),
    Ability('stick_blend',         'Stick Blend',           'A stick-mimic posture confuses the first attack.',                 _disadv_dampen(0.12), ('stick', 'blend'), suits_defense_type=('evasive',)),
    Ability('saw_dust_cloud',      'Saw-Dust Cloud',        'Wood-borer dust thrown to obscure vision.',                        _disadv_dampen(0.10), ('sawdust', 'cloud'), suits_defense_type=('evasive',)),
    Ability('ant_recruit',         'Ant Recruit',           'Triggers nearby ants to harass the attacker.',                     _power(0.03), ('ant', 'recruit'),),
    Ability('treehopper_thorn',    'Treehopper Thorn',      'Thorn-shaped pronotum doubles as a piercing weapon.',              _stat('attack', 4), ('treehopper', 'thorn'), ('piercing',)),
    Ability('aphid_overflow',      'Aphid Overflow',        'Numbers add up — small bonus that compounds.',                     _power(0.02), ('aphid', 'overflow'),),
    Ability('flea_market',         'Flea Market',           'A market of small strikes that aggregate damage.',                 _power(0.03), ('flea', 'market'),),
    Ability('moth_lure',           'Moth Lure',             'Pheromonal lure draws opponent into a kill zone.',                 _stat('cunning', 4), ('moth', 'lure'),),
    Ability('wing_clip',           'Wing Clip',             'Targets opponent wings to ground them.',                           _vs_def('evasive', 0.04), ('wing', 'clip'),),
    Ability('joint_jam',           'Joint Jam',             'A grip aimed to jam the opponent\'s knee joint.',                  _stat('grip', 5), ('joint', 'jam'), ('grappling',)),
    Ability('grip_lock',           'Grip Lock',             'Locks the opponent\'s strike-arm in place.',                       _stat('grip', 6), ('grip', 'lock'), ('grappling',)),
    Ability('thoracic_clamp',      'Thoracic Clamp',        'Pincers around the thorax neutralise mass strikes.',               _stat('grip', 5), ('thoracic', 'clamp'), ('grappling',)),

    # ── A few "anti" abilities tied to specific situations ─────────────
    Ability('anti_swarm_stance',   'Anti-Swarm Stance',     'Body posture defeats small-bug swarming tactics.',                 _vs_def('unarmored', 0.04), ('anti', 'swarm'),),
    Ability('night_eye',           'Night Eye',             'Adapted to low-light fights against bioluminescent bluffs.',       _vs_def('bioluminescent', 0.04), ('night', 'eye'),),
    Ability('heat_seek',           'Heat-Seek',             'IR-pit-style heat detection locates camouflaged opponents.',       _vs_def('evasive', 0.04), ('heat', 'seek', 'pit'),),
    Ability('water_strider',       'Water Strider',         'Skates on water tension; immune to surface-pin grapples.',         _vs_atk('grappling', 0.05), ('water', 'strider'),),
]


# ── Public API ──────────────────────────────────────────────────────────

_BY_SLUG = {a.slug: a for a in _ABILITIES}


def get(slug: str) -> Optional[Ability]:
    return _BY_SLUG.get(slug)


def all_abilities() -> list[Ability]:
    return list(_ABILITIES)


def count() -> int:
    return len(_ABILITIES)


# ── Name resolver ───────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-z]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or '').lower()))


def resolve(
    name: Optional[str],
    attack_type: Optional[str] = None,
    defense_type: Optional[str] = None,
    rng: Optional[random.Random] = None,
) -> Optional[Ability]:
    """Pick the best catalog ability for a free-form name.

    Strategy: exact-name match, then keyword overlap, then a typed fallback
    using the bug's attack_type / defense_type. Returns None only when every
    fallback fails (extremely unlikely once the catalog is loaded).
    """
    if not (name or attack_type or defense_type):
        return None
    rng = rng or random
    name_l = (name or '').strip().lower()
    name_tokens = _tokens(name_l)

    # 1. exact name match
    for a in _ABILITIES:
        if a.name.lower() == name_l:
            return a

    # 2. keyword overlap
    best: tuple[int, Optional[Ability]] = (0, None)
    for a in _ABILITIES:
        if not a.keywords:
            continue
        score = len(set(a.keywords) & name_tokens)
        if score > best[0]:
            best = (score, a)
    if best[0] > 0:
        return best[1]

    # 3. typed fallback — pick something tagged for this attack/defense type
    candidates = [
        a for a in _ABILITIES
        if (attack_type and attack_type in a.suits_attack_type)
        or (defense_type and defense_type in a.suits_defense_type)
    ]
    if candidates:
        return rng.choice(candidates)

    # 4. anything at all
    return rng.choice(_ABILITIES) if _ABILITIES else None


def describe_effect(ability: Ability) -> str:
    """Render the effect into a one-line human-readable string."""
    e = ability.effect
    k = e['kind']
    if k == 'stat_bonus':
        return f"+{e['amount']} {e['stat']}"
    if k == 'power_mult':
        return f"+{int(round(e['pct'] * 100))}% effective power"
    if k == 'type_adv_amp':
        return f"+{int(round(e['pct'] * 100))}% bonus when typed-advantaged"
    if k == 'type_disadv_dampen':
        return f"Recovers {int(round(e['pct'] * 100))}% of a type disadvantage"
    if k == 'size_disadv_dampen':
        return f"Recovers {int(round(e['pct'] * 100))}% of a size disadvantage"
    if k == 'proc_dodge':
        return f"{int(round(e['pct'] * 100))}% chance to negate opponent's type advantage"
    if k == 'counter':
        return f"Reflects {int(round(e['pct'] * 100))}% of opponent's bonus as power"
    if k == 'vs_attack_type':
        return f"+{int(round(e['pct'] * 100))}% power vs {e['type']} attackers"
    if k == 'vs_defense_type':
        return f"+{int(round(e['pct'] * 100))}% power vs {e['type']} defenders"
    return "Subtle modifier"


# ── Battle-engine integration ───────────────────────────────────────────

def apply_effects(
    bug,
    opponent,
    *,
    base_power: float,
    type_multiplier: float,
    size_multiplier: float,
    rng: Optional[random.Random] = None,
    log: Optional[list] = None,
) -> dict:
    """Apply this bug's ability effects to its battle resolution context.

    Returns a dict with adjusted ``base_power``, ``type_multiplier``,
    ``size_multiplier``, ``extra_power_pct``, and ``counter_pct`` (which the
    caller applies to opponent's bonus). The function NEVER mutates the bug
    record. Pass ``log`` to capture human-readable lines about what fired.
    """
    rng = rng or random
    slug = getattr(bug, 'ability_slug', None)
    if not slug:
        return {
            'base_power': base_power,
            'type_multiplier': type_multiplier,
            'size_multiplier': size_multiplier,
            'extra_power_pct': 0.0,
            'counter_pct': 0.0,
        }
    ability = _BY_SLUG.get(slug)
    if not ability:
        return {
            'base_power': base_power,
            'type_multiplier': type_multiplier,
            'size_multiplier': size_multiplier,
            'extra_power_pct': 0.0,
            'counter_pct': 0.0,
        }

    e = ability.effect
    kind = e['kind']
    extra_power_pct = 0.0
    counter_pct = 0.0

    # Stat-style buffs feed back into power as if the stat had been higher.
    # The weighted contribution of each stat in the engine is reused here.
    _STAT_WEIGHT = {
        'attack': 2.0, 'defense': 1.5, 'speed': 1.2,
        'lethality': 1.0, 'grip': 0.8, 'cunning': 0.7,
    }

    if kind == 'stat_bonus':
        weight = _STAT_WEIGHT.get(e['stat'], 1.0)
        base_power += e['amount'] * weight
        if log is not None:
            log.append(f"{ability.name}: +{e['amount']} {e['stat']}")

    elif kind == 'power_mult':
        extra_power_pct += e['pct']
        if log is not None:
            log.append(f"{ability.name}: +{int(round(e['pct'] * 100))}% power")

    elif kind == 'type_adv_amp':
        if type_multiplier > 1.0:
            type_multiplier = 1.0 + (type_multiplier - 1.0) * (1.0 + e['pct'])
            if log is not None:
                log.append(f"{ability.name}: amplifies type advantage")

    elif kind == 'type_disadv_dampen':
        if type_multiplier < 1.0:
            type_multiplier = type_multiplier + e['pct'] * (1.0 - type_multiplier)
            if log is not None:
                log.append(f"{ability.name}: softens type disadvantage")

    elif kind == 'size_disadv_dampen':
        if size_multiplier < 1.0:
            size_multiplier = size_multiplier + e['pct'] * (1.0 - size_multiplier)
            if log is not None:
                log.append(f"{ability.name}: softens size disadvantage")

    elif kind == 'proc_dodge':
        # If the opponent currently has a type advantage on this bug, roll
        # to nullify it for the round.
        if type_multiplier < 1.0 and rng.random() < e['pct']:
            type_multiplier = 1.0
            if log is not None:
                log.append(f"{ability.name}: dodged the type advantage")

    elif kind == 'counter':
        counter_pct = e['pct']
        if log is not None:
            log.append(f"{ability.name}: counter on commit ({int(round(e['pct']*100))}%)")

    elif kind == 'vs_attack_type':
        if getattr(opponent, 'attack_type', None) == e['type']:
            extra_power_pct += e['pct']
            if log is not None:
                log.append(f"{ability.name}: +{int(round(e['pct']*100))}% vs {e['type']}")

    elif kind == 'vs_defense_type':
        if getattr(opponent, 'defense_type', None) == e['type']:
            extra_power_pct += e['pct']
            if log is not None:
                log.append(f"{ability.name}: +{int(round(e['pct']*100))}% vs {e['type']}-defenders")

    return {
        'base_power': base_power,
        'type_multiplier': type_multiplier,
        'size_multiplier': size_multiplier,
        'extra_power_pct': extra_power_pct,
        'counter_pct': counter_pct,
    }
