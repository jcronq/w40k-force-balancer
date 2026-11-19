"""Charge-phase tests."""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


def test_charge_success_engages_both(board_default):
    attacker = make_unit(name="A", models=1,
                         weapons=[make_weapon(melee=True, attacks=1, skill=3,
                                               strength=4, damage=1)])
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
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
    sim.set_board(board)
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
    sim.set_board(board)
    attacker.pos = 10.0; enemy.pos = 0.0   # dist = 14 > 12
    sim.charge_phase(f_a, f_e, round_no=1, rng=RiggedRng([6, 6]))
    # Should have been skipped; no engagement regardless of great roll.
    assert id(enemy) not in attacker.engaged_with
