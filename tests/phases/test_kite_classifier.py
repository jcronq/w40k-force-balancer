"""Tests for fix #2 — audit-worker's Tau kite classifier inside the
`advance_to_optimal_range` movement mode.

Three behaviors:
  1. Longest ranged > 12 AND gap < half-range AND in range -> HOLD POSITION.
  2. Gap < 6 AND no credible melee -> FALL BACK 6" toward own edge.
  3. Otherwise: fall through to "move toward half-range" (unchanged).
"""
from __future__ import annotations

import pytest

import w40k_force_balancer as sim
from w40k_force_balancer.core.doctrine import DEFAULT_DOCTRINE
from w40k_force_balancer.phases.movement import movement_phase

from ..conftest import make_force, make_unit, make_weapon


KITE = DEFAULT_DOCTRINE.merged_with(
    {"movement": {"mode": "advance_to_optimal_range"}}
)


def _setup(mover_weapons, mover_pos, enemy_pos):
    sim.set_board(sim.Board(deployment_gap_in=40))
    mover = make_unit(name="Mover", movement=6, weapons=mover_weapons)
    mover.pos = mover_pos
    mover.doctrine = KITE
    enemy = make_unit(name="Enemy")
    enemy.pos = enemy_pos
    return mover, make_force("A", mover), make_force("B", enemy)


def test_hold_position_when_in_half_range_and_long_weapon(rng):
    """Longest range = 24, half-range = 12. Gap = 10 (in half-range).
    Audit spec: HOLD — do not move, stay stationary."""
    mover, a, b = _setup(
        [make_weapon(range_in=24)],
        mover_pos=0.0, enemy_pos=30.0,
    )
    # gap = 40 - 0 - 30 = 10; half-range = 12; 10 < 12 => HOLD
    movement_phase(a, b, 1, rng)
    assert mover.pos == 0.0
    assert mover.moved_this_turn is False
    assert mover.remained_stationary is True


def test_hold_requires_longer_than_12(rng):
    """Short-range weapon (range = 10) -> rule #1 doesn't fire. We expect
    the default behavior to pick, not HOLD: mover is at gap=3 with no
    melee, so rule #2 (FALL BACK) applies instead."""
    mover, a, b = _setup(
        [make_weapon(range_in=10)],
        mover_pos=0.0, enemy_pos=37.0,
    )
    # gap = 40 - 0 - 37 = 3; range = 10 (not > 12 -> no hold)
    # no credible melee weapon -> FALL BACK 6 (clamped to 0)
    movement_phase(a, b, 1, rng)
    # Already at pos 0, no movement available: step = min(6, pos=0) = 0
    assert mover.pos == 0.0
    # moved stays False because we didn't actually move (clamp).
    assert mover.moved_this_turn is False


def test_fall_back_when_close_and_purely_ranged(rng):
    """Gap < 6, mover is purely ranged (no S>=3 A>=2 melee). Should back
    off 6" toward its own edge."""
    mover, a, b = _setup(
        [make_weapon(range_in=10)],
        mover_pos=15.0, enemy_pos=20.0,
    )
    # gap = 40 - 15 - 20 = 5; range 10 (not > 12); FALL BACK 6" -> pos = 9
    movement_phase(a, b, 1, rng)
    assert mover.pos == pytest.approx(9.0)
    assert mover.moved_this_turn is True
    assert mover.remained_stationary is False


def test_fall_back_skipped_when_credible_melee_present(rng):
    """Gap < 6 but mover has a melee weapon with S>=3 A>=2 — this is a
    Commander with Battlesuit Fist. Should fall through to default move-
    toward-half-range, which closes to the half-range window."""
    mover, a, b = _setup(
        [
            make_weapon(name="Rifle", range_in=10),
            make_weapon(name="Fist", melee=True, range_in=0,
                        attacks=3, strength=6),
        ],
        mover_pos=15.0, enemy_pos=20.0,
    )
    # gap = 5, half-range = 5. |desired_move| = 0 => no move.
    movement_phase(a, b, 1, rng)
    assert mover.pos == 15.0
    assert mover.moved_this_turn is False


def test_hold_only_when_in_range(rng):
    """Gap > weapon range — weapon can't hit, so HOLD rule shouldn't fire.
    Falls through to move-toward-half-range (close by M=6)."""
    # longest range 20 (> 12), half-range 10. Enemy at pos=0, mover at 0
    # => gap = 40. Not in range (> 20). HOLD skipped.
    # Default path: desired_move = 40 - 10 = 30, step = min(6, 30) = 6
    # forward -> pos = 6.
    mover, a, b = _setup(
        [make_weapon(range_in=20)],
        mover_pos=0.0, enemy_pos=0.0,
    )
    movement_phase(a, b, 1, rng)
    assert mover.pos == pytest.approx(6.0)
    assert mover.moved_this_turn is True
