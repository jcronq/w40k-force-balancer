"""Shooting-phase target-priority doctrine tests."""
from __future__ import annotations

import w40k_force_balancer as sim
from w40k_force_balancer.core.doctrine import DEFAULT_DOCTRINE
from w40k_force_balancer.phases.shooting import _pick_target, _threat_value

from ..conftest import make_unit, make_weapon


def test_closest_threat_picks_nearest():
    sim.set_board(sim.Board(deployment_gap_in=40))
    shooter = make_unit(name="Shooter")
    shooter.pos = 0.0
    near = make_unit(name="Near")
    near.pos = 35.0  # gap = 5
    far = make_unit(name="Far")
    far.pos = 10.0   # gap = 30
    pick = _pick_target([near, far], shooter, "closest_threat")
    assert pick.name == "Near"


def test_highest_threat_value_picks_scarier():
    sim.set_board(sim.Board(deployment_gap_in=40))
    shooter = make_unit(name="Shooter")
    shooter.pos = 0.0

    bully = make_unit(
        name="Bully", models=5,
        weapons=[make_weapon(name="bolt", attacks=4, damage=3)],
    )
    bully.pos = 10.0

    chaff = make_unit(
        name="Chaff", models=10,
        weapons=[make_weapon(name="pea", attacks=1, damage=1)],
    )
    chaff.pos = 35.0   # chaff is closer AND dying first by wounds
    chaff._current_model_wounds = 1

    pick = _pick_target([chaff, bully], shooter, "highest_threat_value")
    assert pick.name == "Bully"
    # Sanity: bully's threat value should exceed chaff's.
    assert _threat_value(bully) > _threat_value(chaff)


def test_lowest_wounds_picks_closest_to_dying():
    """Default engine behaviour — min total_wounds (closest-to-dying)."""
    sim.set_board(sim.Board(deployment_gap_in=40))
    shooter = make_unit(name="Shooter")

    healthy = make_unit(name="Healthy", models=5, wounds_per_model=2)
    healthy._current_model_wounds = 2
    hurt = make_unit(name="Hurt", models=1, wounds_per_model=2)
    hurt._current_model_wounds = 1   # total=1 wound

    pick = _pick_target([healthy, hurt], shooter, "lowest_wounds")
    assert pick.name == "Hurt"
