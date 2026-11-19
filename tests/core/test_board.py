"""Board + 1D-distance helpers."""
from __future__ import annotations

import w40k_force_balancer as sim
from tests.conftest import make_unit, make_force


def test_pair_distance_shrinks_as_both_sides_advance(board_default):
    a = make_unit(name="A", models=1); a.pos = 10.0
    b = make_unit(name="B", models=1); b.pos = 8.0
    # gap=24, a.pos=10, b.pos=8, so remaining = 24 - 18 = 6.
    assert sim.pair_distance(a, b) == 6.0


def test_pair_distance_clamped_at_zero(board_default):
    a = make_unit(name="A", models=1); a.pos = 20.0
    b = make_unit(name="B", models=1); b.pos = 20.0
    assert sim.pair_distance(a, b) == 0.0


def test_closest_enemy_within_filters_by_distance(board_default):
    attacker = make_unit(name="A", models=1); attacker.pos = 12.0
    close = make_unit(name="Close", models=1); close.pos = 8.0   # dist = 4
    far = make_unit(name="Far", models=1); far.pos = 0.0          # dist = 12
    enemy = make_force("E", close, far)
    picked = sim.closest_enemy_within(attacker, enemy, 6.0)
    assert picked is close
    # Both out of range:
    assert sim.closest_enemy_within(attacker, enemy, 1.0) is None
