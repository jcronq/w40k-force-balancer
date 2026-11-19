"""Morale-phase tests."""
from __future__ import annotations

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


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
