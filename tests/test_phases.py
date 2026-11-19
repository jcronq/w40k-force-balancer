"""Phase-level tests: movement, charge, fight, morale, overwatch pathing."""
from __future__ import annotations

import random

import pytest

import w40k_sim_v2 as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


def test_movement_normal_move_closes_gap(board_default):
    attacker = make_unit(name="A", models=1, movement=6)
    attacker.weapons = [make_weapon(melee=True, attacks=1, skill=3, strength=4, damage=1)]
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker)
    f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    # Within 12" charge range — normal move 6" allowed.
    attacker.pos = 12.0; enemy.pos = 0.0   # dist = 12
    sim.movement_phase(f_a, f_e, round_no=1, rng=random.Random(0))
    # Expected: moved 6" (M). Advance not chosen since gap=12 == max_weapon_range=0.
    assert attacker.pos == 18.0


def test_movement_advance_when_far(board_default):
    attacker = make_unit(name="A", models=1, movement=6)
    attacker.weapons = [make_weapon(melee=True, attacks=1, skill=3, strength=4, damage=1)]
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker)
    f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=44)
    sim._BOARD = board
    attacker.pos = 0.0; enemy.pos = 0.0   # dist = 44
    rng = RiggedRng([5])   # advance d6 = 5 => M+adv = 11
    sim.movement_phase(f_a, f_e, round_no=1, rng=rng)
    assert attacker.advanced_this_turn
    assert attacker.pos == 11.0


def test_movement_cant_exceed_remaining_gap(board_default):
    """Can't move more than the actual distance to enemy (no walking past)."""
    attacker = make_unit(name="A", models=1, movement=10)
    attacker.weapons = [make_weapon(melee=True, attacks=1, skill=3, strength=4, damage=1)]
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    attacker.pos = 20.0; enemy.pos = 0.0   # dist = 4
    sim.movement_phase(f_a, f_e, round_no=1, rng=random.Random(0))
    # Moved only 4 (can't overrun).
    assert attacker.pos == 24.0


def test_charge_success_engages_both(board_default):
    attacker = make_unit(name="A", models=1,
                         weapons=[make_weapon(melee=True, attacks=1, skill=3,
                                               strength=4, damage=1)])
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    attacker.pos = 18.0; enemy.pos = 0.0   # dist = 6
    rng = RiggedRng([3, 4])   # 2d6=7
    sim.charge_phase(f_a, f_e, round_no=1, rng=rng)
    assert id(enemy) in attacker.engaged_with
    assert id(attacker) in enemy.engaged_with


def test_charge_fail_no_engagement(board_default):
    attacker = make_unit(name="A", models=1,
                         weapons=[make_weapon(melee=True, attacks=1, skill=3,
                                               strength=4, damage=1)])
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    attacker.pos = 12.0; enemy.pos = 0.0   # dist = 12
    rng = RiggedRng([1, 1, 1, 1])   # low rolls; no detachment so no reroll
    sim.charge_phase(f_a, f_e, round_no=1, rng=rng)
    assert id(enemy) not in attacker.engaged_with


def test_charge_declaration_range_12_inches(board_default):
    """Can't declare charge beyond 12"."""
    attacker = make_unit(name="A", models=1,
                         weapons=[make_weapon(melee=True, attacks=1, skill=3,
                                               strength=4, damage=1)])
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    attacker.pos = 10.0; enemy.pos = 0.0   # dist = 14 > 12
    sim.charge_phase(f_a, f_e, round_no=1, rng=RiggedRng([6, 6]))
    # Should have been skipped; no engagement regardless of great roll.
    assert id(enemy) not in attacker.engaged_with


def test_engaged_unit_cannot_shoot_non_pistol(board_default):
    gun = make_weapon(attacks=5, skill=3, strength=10, damage=2, range_in=24)
    attacker = make_unit(name="A", models=1, weapons=[gun])
    enemy = make_unit(name="E", models=5, toughness=4, wounds_per_model=1, save=5)
    attacker.engaged_with.add(id(enemy))
    enemy.engaged_with.add(id(attacker))
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    attacker.pos = 24.0; enemy.pos = 0.0
    sim.shooting_phase(f_a, f_e, round_no=1, rng=random.Random(0))
    # Non-pistol gun didn't fire — enemy unharmed.
    assert enemy.models == 5


def test_morale_below_half_fails_battleshock(board_default):
    """Rule: below-half unit tests 2d6 >= Ld."""
    unit = make_unit(name="Unit", models=10, leadership=8)
    unit.models = 4   # below half
    unit.starting_models = 10
    f = sim.Force(name="F", units=[unit])
    enemy = sim.Force(name="E", units=[])
    # 2+2 = 4 vs Ld8 → fail
    sim.morale_phase(f, enemy, round_no=3, rng=RiggedRng([2, 2]))
    assert unit.battleshocked_until_round == 3


def test_morale_above_half_skips_test(board_default):
    unit = make_unit(name="Unit", models=10, leadership=8)
    unit.models = 6   # above half (6 > 10/2 = 5)
    unit.starting_models = 10
    f = sim.Force(name="F", units=[unit])
    enemy = sim.Force(name="E", units=[])
    sim.morale_phase(f, enemy, round_no=3, rng=RiggedRng([1, 1]))
    assert unit.battleshocked_until_round == 0
