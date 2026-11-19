"""Movement-phase tests."""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


def test_movement_normal_move_closes_gap(board_default):
    attacker = make_unit(name="A", models=1, movement=6)
    attacker.weapons = [make_weapon(melee=True, attacks=1, skill=3, strength=4, damage=1)]
    enemy = make_unit(name="E", models=1)
    f_a = make_force("Fa", attacker)
    f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
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
    sim.set_board(board)
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
    sim.set_board(board)
    attacker.pos = 20.0; enemy.pos = 0.0   # dist = 4
    sim.movement_phase(f_a, f_e, round_no=1, rng=random.Random(0))
    # Moved only 4 (can't overrun).
    assert attacker.pos == 24.0
