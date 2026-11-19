"""Unit-ability tests (section I of the spec)."""
from __future__ import annotations

import random

import pytest

import w40k_sim_v2 as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


# --- Feel No Pain -------------------------------------------------------- #

def test_fnp_ignores_wounds(board_default):
    """Rule: Each wound point ignored on d6 >= N.
    4 unsaved wounds, FNP 4+; rolls 6,5,2,1 => 2 ignored => 2 damage through."""
    w = make_weapon(attacks=4, skill=2, strength=10, damage=1)  # BS2, auto-wound
    tgt = make_unit(name="Tgt", models=2, toughness=3, wounds_per_model=3, save=7,
                    fnp=4)
    # 4 shots hit (2+), 4 wounds (S10 vs T3 crushing), saves auto-fail (Sv7
    # short-circuits — no d6 rolled), 4 damage points enter FNP:
    # rolls 6,5,2,1 => 2 ignored => 2 damage through.
    rng = RiggedRng([2, 2, 2, 2,  5, 5, 5, 5,  6, 5, 2, 1])
    atk = make_unit(name="Atk", models=1)
    f = make_force("F", atk)
    body, _, _ = sim.resolve_shots(atk, w, tgt, 12.0, f, rng)
    assert body == 2


# --- Deep Strike --------------------------------------------------------- #

def test_deep_strike_unit_starts_in_reserves(board_default, catalog):
    import pathlib
    yaml_text = """
name: Test
faction: ADEPTUS_CUSTODES
cp: 4
units:
  - name: "Reserve Squad"
    models: 3
    T: 6
    W: 4
    Sv: 2
    keywords: [INFANTRY, ADEPTUS_CUSTODES]
    abilities: [DEEP_STRIKE]
    weapons:
      - {name: Fist, A: 2, WS: 3, S: 5, AP: 1, D: 1, melee: true}
"""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        p = pathlib.Path(f.name)
    try:
        force = sim.load_force(p, catalog)
    finally:
        os.unlink(p)
    unit = force.units[0]
    assert unit.in_reserves is True
    # After round 1 movement phase, still in reserves (arrival_round=2).
    board = sim.Board()
    sim._BOARD = board
    sim.setup_initial_positions(force)
    enemy = make_force("Enemy", make_unit(name="Dummy"))
    sim.setup_initial_positions(enemy)
    rng = random.Random(0)
    sim.movement_phase(force, enemy, round_no=1, rng=rng)
    assert unit.in_reserves is True
    # Round 2: arrives.
    sim.movement_phase(force, enemy, round_no=2, rng=rng)
    assert unit.in_reserves is False
    # Arrived 9" from enemy edge: gap - 9 = 24 - 9 = 15 (own-side ref).
    assert unit.pos == pytest.approx(15.0)


# --- Stealth ------------------------------------------------------------- #

def test_stealth_minus_one_to_hit_ranged(board_default):
    """Rule: incoming ranged hit rolls get -1 modifier.
    BS3+ weapon vs stealth target: needs 4+ (modifier clamped at ±1).
    Hit roll of 3 fails; 4 succeeds."""
    w = make_weapon(attacks=1, skill=3, strength=4, damage=1)
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=1, save=6,
                    abilities={"STEALTH": {}})
    atk = make_unit(name="Atk", models=1)
    f = make_force("F", atk)
    # Roll 3 — would normally hit at BS3, now needs 4.
    body3, _, _ = sim.resolve_shots(atk, w, tgt, 12.0, f, RiggedRng([3]))
    assert body3 == 0
    # Roll 4 — hits (even under stealth).
    body4, _, _ = sim.resolve_shots(atk, w, tgt, 12.0, f, RiggedRng([4, 5, 1]))
    assert body4 == 1


# --- Fights First -------------------------------------------------------- #

def test_fights_first_resolves_before_normal(board_default):
    """Rule: Fights First units activate in the First tier before normal units.
    Setup: Fast-killing FF unit vs big enemy; FF kills enemy before enemy attacks."""
    # Attacker: 1 model, A=10, WS2, S10, AP5, D5 => will wipe enemy immediately.
    fast_wep = make_weapon(attacks=10, skill=2, strength=10, ap=5, damage=5, melee=True)
    fighter = make_unit(name="FastFighter", models=1, toughness=4, wounds_per_model=5,
                        save=3, weapons=[fast_wep], abilities={"FIGHTS_FIRST": {}})
    enemy_wep = make_weapon(attacks=5, skill=2, strength=10, ap=5, damage=5, melee=True)
    enemy = make_unit(name="Enemy", models=1, toughness=4, wounds_per_model=1,
                      save=5, weapons=[enemy_wep])
    fighter.engaged_with.add(id(enemy))
    enemy.engaged_with.add(id(fighter))
    f1 = make_force("F1", fighter)
    f2 = make_force("F2", enemy)
    rng = random.Random(0)
    sim.fight_phase(f1, f2, round_no=1, rng=rng)
    # Fighter survives (FF killed enemy in first tier before enemy got to swing).
    assert fighter.alive
    assert not enemy.alive


# --- Deadly Demise ------------------------------------------------------- #

def test_deadly_demise_deals_mortals_on_death(board_default):
    """Rule: on destruction, roll d6; if >= threshold, deal N mortals to closest."""
    dying = make_unit(name="Dying", models=1, toughness=4, wounds_per_model=1, save=6,
                      abilities={"DEADLY_DEMISE": {"n": 3, "threshold": 4}})
    victim = make_unit(name="Victim", models=1, toughness=4, wounds_per_model=5, save=6)
    enemy_force = make_force("EF", victim)
    # Set positions so pair_distance works.
    board = sim.Board()
    sim._BOARD = board
    dying.pos = 10.0
    victim.pos = 10.0
    # Rig rng to roll 6 => dies spectacularly.
    rng = RiggedRng([6])
    sim.apply_deadly_demise(dying, enemy_force, rng)
    assert victim.wounds_per_model * victim.models - victim.total_wounds == 3


def test_deadly_demise_whiffs_below_threshold(board_default):
    dying = make_unit(name="Dying", models=1,
                      abilities={"DEADLY_DEMISE": {"n": 3, "threshold": 4}})
    victim = make_unit(name="Victim", models=1, toughness=4, wounds_per_model=5, save=6)
    enemy_force = make_force("EF", victim)
    board = sim.Board()
    sim._BOARD = board
    dying.pos = 0.0; victim.pos = 0.0
    sim.apply_deadly_demise(dying, enemy_force, RiggedRng([3]))
    assert victim.total_wounds == 5


# --- Infiltrators / Scouts ---------------------------------------------- #

def test_infiltrators_start_closer(board_default, catalog):
    import pathlib, tempfile, os
    yaml_text = """
name: Test
units:
  - name: Infil
    models: 5
    T: 3
    W: 1
    Sv: 4
    keywords: [INFANTRY]
    abilities: [INFILTRATORS]
    weapons: [{name: Rifle, A: 1, BS: 3, S: 4, AP: 0, D: 1}]
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        p = pathlib.Path(f.name)
    try:
        force = sim.load_force(p, catalog)
    finally:
        os.unlink(p)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    sim.setup_initial_positions(force)
    assert force.units[0].pos == 9.0


def test_scouts_n_inches_pre_game(board_default, catalog):
    import pathlib, tempfile, os
    yaml_text = """
name: Test
units:
  - name: Scout
    models: 5
    T: 3
    W: 1
    Sv: 4
    keywords: [INFANTRY]
    abilities: [{id: SCOUTS, n: 6}]
    weapons: [{name: Rifle, A: 1, BS: 3, S: 4, AP: 0, D: 1}]
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        p = pathlib.Path(f.name)
    try:
        force = sim.load_force(p, catalog)
    finally:
        os.unlink(p)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    sim.setup_initial_positions(force)
    assert force.units[0].pos == 6.0


# --- For the Greater Good ----------------------------------------------- #

def test_for_the_greater_good_overwatch_hits_on_5_plus(board_default, catalog):
    """When FGG unit is charged with Fire Overwatch strat, it hits on 5+ not 6+."""
    charger = make_unit(name="Charger", models=1, toughness=4, wounds_per_model=5, save=5)
    defender = make_unit(name="Defender", models=1,
                         weapons=[make_weapon(attacks=1, skill=4, strength=10,
                                              damage=1, range_in=24)],
                         abilities={"FOR_THE_GREATER_GOOD": {}})
    charger.pos = 20.0; defender.pos = 0.0
    # Minimal detachment that includes FIRE_OVERWATCH
    det = catalog.detachments["montka"]
    cf = sim.Force(name="Chargers", units=[charger])
    df = sim.Force(name="Defenders", units=[defender], detachment=det, cp=3)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    rng = RiggedRng([5,  5,  1])  # hit 5 (passes under FGG 5+ overwatch), wound, no save
    sim._do_overwatch(charger, defender, df, cf, round_no=1, rng=rng, verbose=False)
    # Charger took at least 1 damage: starting W=5, now less.
    assert charger.total_wounds < 5


# --- Markerlight -------------------------------------------------------- #

def test_markerlight_places_tokens(board_default):
    """Rule: pathfinder-like units place markers on 4+, one roll per model."""
    marker_weapon = make_weapon(attacks=2, skill=4, strength=5, ap=0, damage=1)
    markers = make_unit(name="Pathfinders", models=5, toughness=3, wounds_per_model=1,
                        save=5, weapons=[marker_weapon],
                        abilities={"MARKERLIGHT": {"n": 1}})
    victim = make_unit(name="Victim", models=1, toughness=4, wounds_per_model=5, save=6)
    atk_force = sim.Force(name="Atk", faction="TAU_EMPIRE", units=[markers])
    df_force = sim.Force(name="Def", units=[victim])
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    markers.pos = 10.0
    victim.pos = 0.0
    # 5 marker rolls: 4,4,4,2,1 => 3 placed (capped at 3)
    rng = RiggedRng([4, 4, 4, 2, 1,   # markerlight rolls
                     # followed by shot rolls for the remaining weapon shots
                     1, 1, 1, 1, 1,
                     1, 1, 1, 1, 1,
                     1, 1, 1, 1, 1])
    sim._shoot_weapon_set(markers, [marker_weapon], atk_force, df_force,
                          round_no=1, rng=rng, verbose=False)
    assert atk_force.markerlights[id(victim)] == 3
