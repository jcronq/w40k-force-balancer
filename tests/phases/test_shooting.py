"""Shooting-phase tests (engagement + pistol gating)."""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


def test_engaged_unit_cannot_shoot_non_pistol(board_default):
    gun = make_weapon(attacks=5, skill=3, strength=10, damage=2, range_in=24)
    attacker = make_unit(name="A", models=1, weapons=[gun])
    enemy = make_unit(name="E", models=5, toughness=4, wounds_per_model=1, save=5)
    attacker.engaged_with.add(id(enemy))
    enemy.engaged_with.add(id(attacker))
    f_a = make_force("Fa", attacker); f_e = make_force("Fe", enemy)
    board = sim.Board(deployment_gap_in=24)
    sim.set_board(board)
    attacker.pos = 24.0; enemy.pos = 0.0
    sim.shooting_phase(f_a, f_e, round_no=1, rng=random.Random(0))
    # Non-pistol gun didn't fire — enemy unharmed.
    assert enemy.models == 5
