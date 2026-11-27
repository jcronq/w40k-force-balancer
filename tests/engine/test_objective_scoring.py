"""Tests for the Chapter-Approved-style objective VP scoring.

Covers fix #1 — replaces the pre-fix total_wounds tiebreaker with a real
primary-VP model:
  * 3 objectives at gap/4, gap/2, 3*gap/4 along the approach axis.
  * Each round-end: whoever has more OC within 3" of an objective holds
    it and scores 5 VP; ties are contested (0 VP).
  * Tabling an opposing force is an auto-win at any point.
  * At game end, higher VP wins; exact VP tie falls back to wounds.
"""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from w40k_force_balancer.engine.game import (
    OBJECTIVE_HOLD_VP,
    _default_objectives,
    _oc_contribution,
    _score_round,
)
from w40k_force_balancer.engine.logger import JsonlLogger

from ..conftest import make_force, make_unit


def _std_board() -> sim.Board:
    b = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    sim.set_board(b)
    return b


def test_default_objectives_quarter_half_three_quarter_positions():
    b = _std_board()
    obs = _default_objectives(b)
    assert obs == [6.0, 12.0, 18.0]


def test_oc_contribution_counts_only_within_three_inches():
    u = make_unit(name="X", models=3, oc=2)
    # A unit at pos=5 vs objective at pos_from_a=6 => distance 1.0" — in
    u.pos = 5.0
    assert _oc_contribution(u, 6.0, True, 24.0) == 6    # 2 oc * 3 models
    # Move 4" further from objective: distance 3.0 (boundary — within 3")
    u.pos = 3.0
    assert _oc_contribution(u, 6.0, True, 24.0) == 6
    # Over: distance 4.0 => 0
    u.pos = 2.0
    assert _oc_contribution(u, 6.0, True, 24.0) == 0


def test_oc_contribution_handles_side_b_projection():
    u = make_unit(name="Y", models=4, oc=1)
    # B unit at pos=5 projects to 24-5 = 19 from A's edge.
    u.pos = 5.0
    # Objective at 18 from A's edge => distance 1" (holds)
    assert _oc_contribution(u, 18.0, False, 24.0) == 4
    # Objective at 12 (center) => distance 7" (out of range)
    assert _oc_contribution(u, 12.0, False, 24.0) == 0


def test_oc_contribution_zero_for_reserves_or_dead():
    u = make_unit(name="Z", models=3, oc=2)
    u.pos = 6.0
    u.in_reserves = True
    assert _oc_contribution(u, 6.0, True, 24.0) == 0
    u.in_reserves = False
    u.models = 0   # dead
    assert _oc_contribution(u, 6.0, True, 24.0) == 0


def test_score_round_assigns_vp_by_oc_majority():
    a_holder = make_unit(name="AHolder", models=5, oc=2); a_holder.pos = 12.0
    b_holder = make_unit(name="BHolder", models=3, oc=2); b_holder.pos = 6.0
    # a_holder: 10 OC at pos_from_a=12 -> holds center.
    # b_holder: 6 OC at pos_from_a=24-6=18 -> holds far-side marker.
    a = make_force("A", a_holder)
    b = make_force("B", b_holder)
    a_vp, b_vp, details = _score_round(a, b, [6.0, 12.0, 18.0], 24.0)
    assert a_vp == OBJECTIVE_HOLD_VP      # center only
    assert b_vp == OBJECTIVE_HOLD_VP      # far only
    holders = [d["holder"] for d in details]
    assert holders == ["contested", "A", "B"]


def test_score_round_ties_are_contested():
    a_u = make_unit(name="AU", models=2, oc=2); a_u.pos = 12.0
    b_u = make_unit(name="BU", models=4, oc=1); b_u.pos = 12.0
    # a_u: 4 OC at center; b_u: 4 OC at center (24-12=12) — tie
    a = make_force("A", a_u)
    b = make_force("B", b_u)
    a_vp, b_vp, details = _score_round(a, b, [12.0], 24.0)
    assert a_vp == 0
    assert b_vp == 0
    assert details[0]["holder"] == "contested"


def test_game_end_carries_primary_vp(tmp_path):
    """The game_end event exposes both sides' primary VP totals."""
    au = make_unit(name="AHold", models=5, oc=2, movement=6); au.pos = 0.0
    bu = make_unit(name="BStand", models=1, oc=1); bu.pos = 0.0
    a = make_force("A", au)
    b = make_force("B", bu)
    board = _std_board()
    path = tmp_path / "g.jsonl"
    with JsonlLogger(path) as log:
        sim.simulate_game(a, b, board, rounds=5, a_goes_first=True,
                          rng=random.Random(0), logger=log, seed=0)
    import json
    events = [json.loads(line) for line in path.read_text().splitlines()]
    end = events[-1]
    assert "a_vp" in end and "b_vp" in end
    # Also at least one primary_score event logged per round.
    primaries = [e for e in events if e.get("type") == "primary_score"]
    assert len(primaries) >= 1
    for p in primaries:
        assert "a_vp_total" in p and "b_vp_total" in p


def test_tabling_still_wins_without_needing_vp():
    """If A kills every B unit outright, A wins regardless of VP."""
    attacker = make_unit(
        name="BigGuns", models=1, toughness=3, wounds_per_model=10, save=2,
        oc=0,
        weapons=[sim.Weapon(
            name="Plasma", attacks=20, skill=2, strength=9, ap=3,
            damage=5, range_in=48,
        )],
    )
    attacker.pos = 0.0
    victim = make_unit(name="Squishy", models=1, toughness=3,
                       wounds_per_model=1, save=6, oc=5)
    victim.pos = 0.0
    a = make_force("A", attacker)
    b = make_force("B", victim)
    board = _std_board()
    r = sim.simulate_game(a, b, board, rounds=5, a_goes_first=True,
                          rng=random.Random(0), seed=0)
    assert r == "A"
