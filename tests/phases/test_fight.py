"""Fight-phase integration test — engaged units trade damage."""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force


def test_fight_activation_damages_engaged_target(board_default):
    """Two engaged normal-tier units: active attacker's melee weapon lands at
    least some damage on the defender over a deterministic seed."""
    sword = make_weapon(melee=True, attacks=4, skill=2, strength=6, ap=2, damage=1)
    attacker = make_unit(name="A", models=1, toughness=4, wounds_per_model=3, save=3,
                         weapons=[sword])
    victim = make_unit(name="V", models=5, toughness=3, wounds_per_model=1, save=5)
    attacker.engaged_with.add(id(victim))
    victim.engaged_with.add(id(attacker))
    fa = make_force("Fa", attacker)
    fv = make_force("Fv", victim)
    sim.fight_phase(fa, fv, round_no=1, rng=random.Random(42))
    # Deterministic under seed=42: at least 1 model of the squad dies.
    assert victim.models < 5
