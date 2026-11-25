"""Charge-phase doctrine policy tests."""
from __future__ import annotations

import w40k_force_balancer as sim
from w40k_force_balancer.core.doctrine import DEFAULT_DOCTRINE
from w40k_force_balancer.load.doctrines import load_doctrine
from w40k_force_balancer.phases.charge import charge_phase

from ..conftest import make_force, make_unit, make_weapon


def test_charge_policy_never_skips_charge(rng):
    sim.set_board(sim.Board(deployment_gap_in=24))
    charger = make_unit(
        name="Would-charge", movement=6,
        weapons=[make_weapon(melee=True, range_in=0, attacks=2)],
    )
    enemy = make_unit(name="Enemy")
    # Position: charger 18" forward, enemy 0 -> gap = 6 (2d6 will almost always make it).
    charger.pos = 18.0
    enemy.pos = 0.0
    charger.doctrine = DEFAULT_DOCTRINE.merged_with({"charge": {"policy": "never"}})
    a = make_force("A", charger)
    b = make_force("B", enemy)
    charge_phase(a, b, 1, rng)
    assert charger.engaged_with == set()
    assert id(enemy) not in charger.engaged_with


def test_charge_policy_always_possible_charges_when_in_range(rigged):
    sim.set_board(sim.Board(deployment_gap_in=24))
    charger = make_unit(
        name="Rusher", movement=6,
        weapons=[make_weapon(melee=True, range_in=0, attacks=2)],
    )
    enemy = make_unit(name="Enemy")
    charger.pos = 18.0
    enemy.pos = 0.0   # gap = 6
    charger.doctrine = load_doctrine("rush")
    a = make_force("A", charger)
    b = make_force("B", enemy)
    # Force a successful charge roll: 2d6 = rig roll 5+5 = 10 >= 6.
    charge_phase(a, b, 1, rigged([5, 5]))
    assert id(enemy) in charger.engaged_with


def test_charge_policy_never_on_gunline(rigged):
    """Load the actual gunline doctrine; a gunline unit never charges."""
    sim.set_board(sim.Board(deployment_gap_in=24))
    unit = make_unit(
        name="Gunner",
        weapons=[make_weapon(range_in=24), make_weapon(melee=True, range_in=0, attacks=1)],
    )
    enemy = make_unit(name="Enemy")
    unit.pos = 18.0
    enemy.pos = 0.0
    unit.doctrine = load_doctrine("gunline")
    a = make_force("A", unit)
    b = make_force("B", enemy)
    charge_phase(a, b, 1, rigged([6, 6]))
    # Even on a 12 (auto-success), gunline never declares the charge.
    assert id(enemy) not in unit.engaged_with
