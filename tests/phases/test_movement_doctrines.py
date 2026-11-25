"""Movement phase: pin each doctrine mode produces the expected post-move pos."""
from __future__ import annotations

import pytest

import w40k_force_balancer as sim
from w40k_force_balancer.core.doctrine import (
    DEFAULT_DOCTRINE,
    Doctrine,
    DoctrineCharge,
    DoctrineFallBack,
    DoctrineMovement,
    DoctrineShooting,
)
from w40k_force_balancer.load.doctrines import load_doctrine
from w40k_force_balancer.phases.movement import movement_phase

from ..conftest import make_force, make_unit, make_weapon


def _setup(mover_doctrine: Doctrine, enemy_pos: float = 0.0, mover_pos: float = 0.0):
    sim.set_board(sim.Board(deployment_gap_in=40))
    mover = make_unit(name="Mover", movement=6, weapons=[make_weapon(range_in=24)])
    mover.pos = mover_pos
    mover.doctrine = mover_doctrine
    enemy = make_unit(name="Enemy")
    enemy.pos = enemy_pos
    a = make_force("A", mover)
    b = make_force("B", enemy)
    return mover, a, b


def test_stationary_mode_does_not_move(rng):
    d = DEFAULT_DOCTRINE.merged_with({"movement": {"mode": "stationary"}})
    mover, a, b = _setup(d)
    movement_phase(a, b, 1, rng)
    assert mover.pos == 0.0
    assert mover.remained_stationary is True


def test_advance_toward_moves_full_M(rng):
    d = DEFAULT_DOCTRINE.merged_with({"movement": {"mode": "advance_toward",
                                                   "advance_roll": False}})
    mover, a, b = _setup(d)
    movement_phase(a, b, 1, rng)
    # Gap starts at 40, within charge range after M (34 remaining).
    # No advance_roll so step is exactly M=6.
    assert mover.pos == 6.0
    assert mover.moved_this_turn is True
    assert mover.advanced_this_turn is False


def test_advance_toward_with_roll_only_advances_when_out_of_charge(rigged):
    """If gap > 12, +d6 Advance. If gap <= 12, plain M (so charge stays legal)."""
    d = DEFAULT_DOCTRINE.merged_with({"movement": {"mode": "advance_toward",
                                                   "advance_roll": True}})
    # Far: gap=40. Should advance with +d6.
    mover_far, a_far, b_far = _setup(d)
    movement_phase(a_far, b_far, 1, rigged([4]))   # d6 = 4
    assert mover_far.pos == pytest.approx(10.0)    # 6 + 4
    assert mover_far.advanced_this_turn is True

    # Close: gap=10 (< 12). Should NOT advance, just plain M.
    mover_close, a_close, b_close = _setup(d, enemy_pos=30.0)
    # gap = 40 - 0 - 30 = 10
    movement_phase(a_close, b_close, 1, rigged([5]))
    assert mover_close.pos == pytest.approx(6.0)   # plain M, no +d6
    assert mover_close.advanced_this_turn is False


def test_advance_away_backs_up(rng):
    d = DEFAULT_DOCTRINE.merged_with({"movement": {"mode": "advance_away"}})
    # Mover starts 10" forward; should back up.
    mover, a, b = _setup(d, mover_pos=10.0)
    movement_phase(a, b, 1, rng)
    assert mover.pos == pytest.approx(4.0)    # 10 - 6 = 4
    assert mover.moved_this_turn is True


def test_advance_away_clamps_at_deployment_edge(rng):
    d = DEFAULT_DOCTRINE.merged_with({"movement": {"mode": "advance_away"}})
    mover, a, b = _setup(d, mover_pos=2.0)
    movement_phase(a, b, 1, rng)
    assert mover.pos == 0.0


def test_advance_to_optimal_range_with_ranged_weapon(rng):
    """Half-range of 24" weapon = 12". If gap > 12, advance toward (close to 12).
    If gap < 12, back off to 12."""
    d = DEFAULT_DOCTRINE.merged_with({"movement": {"mode": "advance_to_optimal_range"}})
    # Far: gap=40, optimal=12 -> want to close 28", limited by M=6.
    mover_far, a_far, b_far = _setup(d)
    movement_phase(a_far, b_far, 1, rng)
    assert mover_far.pos == pytest.approx(6.0)
    assert mover_far.moved_this_turn is True

    # Close: gap=5, optimal=12 -> need to back up 7", limited by M=6.
    mover_close, a_close, b_close = _setup(d, enemy_pos=35.0)
    # gap = 40 - 0 - 35 = 5. Need to back to pos = -7, clamped to 0 but M=6.
    movement_phase(a_close, b_close, 1, rng)
    # Backward move of 6 lands at pos = -6, clamped to 0.
    assert mover_close.pos == pytest.approx(0.0)


def test_fall_back_never_doctrine_stays_engaged(rng):
    sim.set_board(sim.Board(deployment_gap_in=40))
    me = make_unit(name="Me", movement=6,
                   weapons=[make_weapon(melee=True, range_in=0, attacks=1)])
    foe = make_unit(name="Foe",
                    weapons=[make_weapon(melee=True, range_in=0, attacks=20)])
    me.pos = 20.0
    foe.pos = 20.0
    me.engaged_with.add(id(foe))
    foe.engaged_with.add(id(me))
    me.doctrine = DEFAULT_DOCTRINE.merged_with({"fall_back": {"trigger": "never"}})
    a = make_force("A", me)
    b = make_force("B", foe)
    movement_phase(a, b, 1, rng)
    assert me.engaged_with == {id(foe)}   # still engaged
    assert me.pos == 20.0                  # didn't back off


def test_fall_back_when_engaged_always_falls_back(rng):
    sim.set_board(sim.Board(deployment_gap_in=40))
    me = make_unit(name="Me", movement=6,
                   weapons=[make_weapon(melee=True, range_in=0, attacks=50)])
    foe = make_unit(name="Foe",
                    weapons=[make_weapon(melee=True, range_in=0, attacks=1)])
    me.pos = 20.0
    foe.pos = 20.0
    me.engaged_with.add(id(foe))
    foe.engaged_with.add(id(me))
    # me's melee math says WE should win (50 vs 1); but doctrine forces Fall Back.
    me.doctrine = DEFAULT_DOCTRINE.merged_with({"fall_back": {"trigger": "when_engaged"}})
    a = make_force("A", me)
    b = make_force("B", foe)
    movement_phase(a, b, 1, rng)
    assert me.engaged_with == set()        # cleared
    assert me.advanced_this_turn is True   # Fall Back counts as advance for sim


def test_fall_back_only_if_losing_matches_old_heuristic(rng):
    """only_if_losing = DEFAULT_DOCTRINE behavior = current engine finding #5."""
    sim.set_board(sim.Board(deployment_gap_in=40))
    me = make_unit(name="Me", movement=6,
                   weapons=[make_weapon(melee=True, range_in=0, attacks=1)])
    foe = make_unit(name="Foe",
                    weapons=[make_weapon(melee=True, range_in=0, attacks=50)])
    me.pos = 20.0
    foe.pos = 20.0
    me.engaged_with.add(id(foe))
    foe.engaged_with.add(id(me))
    me.doctrine = DEFAULT_DOCTRINE
    a = make_force("A", me)
    b = make_force("B", foe)
    movement_phase(a, b, 1, rng)
    # Losing the math -> Fall Back triggers.
    assert me.engaged_with == set()
    assert me.advanced_this_turn is True
