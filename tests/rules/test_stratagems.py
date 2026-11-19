"""Stratagem + CP economy tests (section K of the spec)."""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


# --- CP economy --------------------------------------------------------- #

def test_cp_defaults_to_four():
    f = sim.Force(name="F", units=[])
    assert f.cp == 4


def test_command_phase_grants_cp_from_round_two(catalog, board_default):
    f = sim.Force(name="F", units=[], cp=4,
                  detachment=catalog.detachments["montka"])
    enemy = sim.Force(name="E", units=[])
    sim.command_phase(f, enemy, round_no=1, rng=random.Random(0))
    assert f.cp == 4   # no gain round 1
    sim.command_phase(f, enemy, round_no=2, rng=random.Random(0))
    assert f.cp == 5


# --- Fire Overwatch ----------------------------------------------------- #

def test_fire_overwatch_spends_cp_and_fires(catalog, board_default):
    charger = make_unit(name="Charger", models=1, toughness=4, wounds_per_model=5, save=5)
    defender = make_unit(name="Defender", models=1,
                         weapons=[make_weapon(attacks=4, skill=4, strength=10,
                                              damage=1, range_in=24)])
    det = catalog.detachments["montka"]
    cf = sim.Force(name="Chargers", units=[charger])
    df = sim.Force(name="Defenders", units=[defender], detachment=det, cp=3)
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    charger.pos = 20.0; defender.pos = 0.0
    # 4 shots overwatching, need 6+; rolls 6,6,1,1 => 2 hits
    # Then 2 wound rolls at 2+ (S10 vs T4), rolls 5,5 => both wound
    # Then 2 save rolls, fail Sv5 if roll < 5, rolls 1,1 => 2 fails => 2 damage
    rng = RiggedRng([6, 6, 1, 1,  5, 5,  1, 1])
    sim._do_overwatch(charger, defender, df, cf, round_no=1, rng=rng, verbose=False)
    assert df.cp == 2
    assert charger.total_wounds == 3


def test_fire_overwatch_not_in_detachment_noop(catalog, board_default):
    charger = make_unit(name="Charger", models=1)
    defender = make_unit(name="Defender", models=1,
                         weapons=[make_weapon(attacks=1, skill=4, strength=10,
                                              damage=1, range_in=24)])
    det = catalog.detachments["shield_host"]   # Shield Host has no FIRE_OVERWATCH
    cf = sim.Force(name="Chargers", units=[charger])
    df = sim.Force(name="Defenders", units=[defender], detachment=det, cp=3)
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    charger.pos = 20.0; defender.pos = 0.0
    sim._do_overwatch(charger, defender, df, cf, round_no=1, rng=random.Random(0), verbose=False)
    assert df.cp == 3   # unspent


# --- Rapid Ingress ----------------------------------------------------- #

def test_rapid_ingress_arrives_round_one(catalog, board_default):
    reserve = make_unit(name="Reserve", models=3,
                        abilities={"DEEP_STRIKE": {"arrival_round": 2, "range_in": 9}},
                        weapons=[make_weapon(melee=True, attacks=2, skill=3,
                                             strength=5, damage=1)])
    reserve.in_reserves = True
    det = catalog.detachments["shield_host"]
    f = sim.Force(name="F", units=[reserve], detachment=det, cp=3)
    enemy = sim.Force(name="E", units=[make_unit(name="Dummy")])
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    sim.command_phase(f, enemy, round_no=1, rng=random.Random(0))
    assert reserve.in_reserves is False
    assert reserve.pos == pytest.approx(15.0)
    assert f.cp == 2
    assert f.rapid_ingress_used is True


# --- Heroic Intervention ----------------------------------------------- #

def test_heroic_intervention_engages_nearby_charger(catalog, board_default):
    det = catalog.detachments["shield_host"]
    # Enemy charger approaches at range 3" (within HI).
    charger_w = make_weapon(melee=True, attacks=1, skill=3, strength=4, damage=1)
    charger = make_unit(name="Charger", models=1, weapons=[charger_w])
    hero_w = make_weapon(melee=True, attacks=5, skill=2, strength=6, ap=1, damage=2)
    hero = make_unit(name="Hero", models=1, weapons=[hero_w])
    cf = sim.Force(name="Chargers", units=[charger])
    df = sim.Force(name="Heroes", units=[hero], detachment=det, cp=3)
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    # Put charger at distance=2 from hero.
    charger.pos = 22.0
    hero.pos = 0.0
    # Charger is NOT engaged yet; this models the moment after enemy's charge.
    # Heroic Intervention is triggered during charge_phase when enemy charges
    # a different unit, but we test the mechanism directly:
    sim.charge_phase(cf, df, round_no=1, rng=random.Random(1), verbose=False)
    # Hero should now be engaged with charger (triggered by HI since
    # charger started within 3" and didn't complete melee).
    assert id(charger) in hero.engaged_with or id(hero) in charger.engaged_with


# --- Insane Bravery ---------------------------------------------------- #

def test_insane_bravery_auto_passes_battleshock(catalog, board_default):
    unit = make_unit(name="Unit", models=10, leadership=15)   # Ld15 = auto-fail
    unit.models = 2   # below half of 10
    unit.starting_models = 10
    det = catalog.detachments["shield_host"]
    f = sim.Force(name="F", units=[unit], detachment=det, cp=3)
    enemy = sim.Force(name="E", units=[])
    # Rig the 2d6 to roll 2 (1+1) which fails vs Ld15.
    rng = RiggedRng([1, 1])
    sim.morale_phase(f, enemy, round_no=1, rng=rng)
    # With Insane Bravery available, should have been auto-passed.
    assert unit.battleshocked_until_round == 0
    assert f.cp == 2


# --- Command Re-roll --------------------------------------------------- #

def test_command_reroll_on_failed_charge(catalog, board_default):
    det = catalog.detachments["shield_host"]
    attacker = make_unit(name="Attacker", models=1,
                          weapons=[make_weapon(melee=True, attacks=1, skill=3,
                                               strength=4, damage=1)])
    defender = make_unit(name="Def", models=1)
    f = sim.Force(name="F", units=[attacker], detachment=det, cp=3)
    df = sim.Force(name="D", units=[defender])
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    # Position: 8" apart. Need 8 on 2d6 to charge.
    attacker.pos = 16.0; defender.pos = 0.0
    # First 2d6 rolls 3 (1+2) → fail. Reroll yields 10 (5+5) → success.
    rng = RiggedRng([1, 2,  5, 5])
    sim.charge_phase(f, df, round_no=1, rng=rng)
    assert id(defender) in attacker.engaged_with
    assert f.cp == 2   # spent 1 on reroll


# --- Grenade ---------------------------------------------------------- #

def test_grenade_strat_fires_at_infantry(catalog, board_default):
    det = catalog.detachments["montka"]
    thrower_w = make_weapon(attacks=0, skill=4, strength=4, damage=1, range_in=24)
    thrower = make_unit(name="Breacher", models=5,
                        keywords=["INFANTRY", "GRENADES"],
                        weapons=[thrower_w])
    victim = make_unit(name="Victim", models=10, toughness=3,
                       wounds_per_model=1, save=5, keywords=["INFANTRY"])
    f = sim.Force(name="F", units=[thrower], detachment=det, cp=3, faction="TAU_EMPIRE")
    df = sim.Force(name="D", units=[victim])
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    # Position within 8".
    thrower.pos = 17.0; victim.pos = 0.0   # dist = 7
    # Not enough non-grenade shots to care; rig the grenade 6-shot roll
    # pattern: hits (all 6s), wounds, saves.
    rng = RiggedRng([6, 6, 6, 6, 6, 6,     # 6 hits
                     5, 5, 5, 5, 5, 5,     # 6 wounds
                     1, 1, 1, 1, 1, 1])    # 6 saves fail
    sim.shooting_phase(f, df, round_no=1, rng=rng)
    # Grenade should have consumed 1 CP and dealt real damage.
    assert f.cp == 2
    assert victim.models < 10
