"""Tests for fix #3 — Grenade stratagem uses the 10e rule:

  * Pick an enemy INFANTRY unit within 8" of a friendly INFANTRY GRENADES
    unit, roll 6d6; each 4+ deals 1 mortal wound.
  * Mortals bypass saves AND invuln (route via mortal_body pool).
  * Costs 1 CP, once per battle round per player.
"""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from w40k_force_balancer.phases.shooting import shooting_phase

from ..conftest import make_force, make_unit, make_weapon, RiggedRng


def _board_close():
    b = sim.Board(deployment_gap_in=14)
    sim.set_board(b)
    return b


def _grenade_force(unit) -> sim.Force:
    """Build an attacker force with a GRENADE stratagem available."""
    det = sim.Detachment(
        name="TestDet", faction="TEST",
        army_ability="", stratagems=["GRENADE"],
    )
    return sim.Force(name="Grenaders", units=[unit], cp=4, detachment=det)


def test_grenade_rolls_six_d6_and_only_4plus_deal_mortals():
    """All 6s on the 6d6 -> 6 mortal wounds; all 1s -> 0."""
    attacker = make_unit(
        name="Breachers", models=10, keywords=["INFANTRY", "GRENADES"],
        weapons=[make_weapon(melee=False, range_in=10)],
    )
    attacker.pos = 7.0
    target = make_unit(
        name="EnemyInfantry", models=6, keywords=["INFANTRY"],
        toughness=4, wounds_per_model=1, save=3, oc=1,
    )
    target.pos = 0.0
    _board_close()
    a = _grenade_force(attacker)
    b = make_force("B", target)

    # Rig 6d6 to all come up 6 -> 6 mortals -> 6 models dead (W=1 each).
    rigged = RiggedRng([6, 6, 6, 6, 6, 6], fallback=1)
    shooting_phase(a, b, round_no=1, rng=rigged)
    assert target.models == 0


def test_grenade_misses_do_zero_damage():
    attacker = make_unit(
        name="Breachers", models=10, keywords=["INFANTRY", "GRENADES"],
        weapons=[make_weapon(melee=False, range_in=10)],
    )
    attacker.pos = 7.0
    target = make_unit(
        name="EnemyInfantry", models=6, keywords=["INFANTRY"],
        toughness=4, wounds_per_model=1, save=3, oc=1,
    )
    target.pos = 0.0
    _board_close()
    a = _grenade_force(attacker)
    b = make_force("B", target)

    pre_wounds = target.total_wounds
    # All 1s -> 0 mortals. BUT shooting_phase will also fire the breacher's
    # ranged weapon. Patch the rigged rng so the subsequent to-hit / wound
    # / save rolls all fail (all 1s). The fallback=1 ensures nothing
    # afterwards passes any roll.
    rigged = RiggedRng([1, 1, 1, 1, 1, 1], fallback=1)
    shooting_phase(a, b, round_no=1, rng=rigged)
    # No grenade damage; no normal-weapon damage because all 1s miss.
    assert target.total_wounds == pre_wounds


def test_grenade_bypasses_armor_and_invuln():
    """Target has a 2+ Sv and 4++ invuln — mortals should still land."""
    attacker = make_unit(
        name="Breachers", models=10, keywords=["INFANTRY", "GRENADES"],
        weapons=[make_weapon(melee=False, range_in=10)],
    )
    attacker.pos = 7.0
    target = make_unit(
        name="BigBoy", models=1, keywords=["INFANTRY"],
        toughness=6, wounds_per_model=10, save=2, inv_save=4, oc=1,
    )
    target.pos = 0.0
    _board_close()
    a = _grenade_force(attacker)
    b = make_force("B", target)

    # 6d6 all 6s -> 6 mortals. No save rolled.
    rigged = RiggedRng([6, 6, 6, 6, 6, 6], fallback=1)
    shooting_phase(a, b, round_no=1, rng=rigged)
    # 10 starting wounds - 6 mortals = 4 remaining.
    assert target._current_model_wounds == 4


def test_grenade_requires_target_within_eight_inches():
    attacker = make_unit(
        name="Breachers", models=10, keywords=["INFANTRY", "GRENADES"],
        weapons=[make_weapon(melee=False, range_in=10)],
    )
    attacker.pos = 0.0
    target = make_unit(
        name="EnemyInfantry", models=6, keywords=["INFANTRY"],
        toughness=4, wounds_per_model=1, save=3, oc=1,
    )
    target.pos = 0.0   # gap = 14 (board) > 8
    _board_close()
    a = _grenade_force(attacker)
    b = make_force("B", target)
    starting_cp = a.cp

    # Rolls that would deal 6 MW if the strat fired.
    rigged = RiggedRng([6, 6, 6, 6, 6, 6], fallback=1)
    shooting_phase(a, b, round_no=1, rng=rigged)
    # CP not spent on GRENADE (strat gated by distance).
    assert a.cp == starting_cp
    # Target still at full strength on mortal-only accounting (weapon out of range too).
    assert target.models == 6


def test_grenade_target_must_be_infantry():
    """Vehicle targets within 8" don't get grenaded."""
    attacker = make_unit(
        name="Breachers", models=10, keywords=["INFANTRY", "GRENADES"],
        weapons=[make_weapon(melee=False, range_in=10)],
    )
    attacker.pos = 7.0
    tank = make_unit(
        name="Tank", models=1, keywords=["VEHICLE"],
        toughness=10, wounds_per_model=12, save=3, oc=3,
    )
    tank.pos = 0.0
    _board_close()
    a = _grenade_force(attacker)
    b = make_force("B", tank)

    rigged = RiggedRng([6, 6, 6, 6, 6, 6], fallback=1)
    starting_cp = a.cp
    shooting_phase(a, b, round_no=1, rng=rigged)
    # GRENADE must not fire against a VEHICLE.
    assert a.cp == starting_cp
