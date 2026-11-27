"""End-to-end integration tests — a full Custodes-vs-T'au game runs through
the six-phase loop deterministically, and the headline many-sim blend
matches the snapshotted "A dominates" shape under the shipped v2 forces.

These exist to pin behavior during future refactors: a pure-move refactor
MUST preserve these numbers; a rules change MUST re-baseline them.
"""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim


def test_full_game_runs_without_error_and_picks_a_winner(catalog, repo_root):
    """Smoke: one full game on the shipped v2 forces returns a valid result."""
    custodes = sim.load_force(repo_root / "forces" / "force_custodes_2024cp_v2.yaml", catalog)
    tau = sim.load_force(repo_root / "forces" / "force_tau_2024cp_v2.yaml", catalog)
    board = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    result = sim.simulate_game(custodes, tau, board, rounds=5, a_goes_first=True,
                               rng=random.Random(0))
    assert result in ("A", "B", "draw")


def test_sim_many_v2_custodes_tau_balanced_on_fixed_engine(catalog, repo_root):
    """500-sim blend on shipped v2 forces, Custodes-first, seed=0.

    Baseline re-pinned 2026-11-27 after the engine-correctness fixpack:
      * objective-based VP scoring (replaces total_wounds tiebreaker)
      * kite-doctrine HOLD + 6" FALL BACK classifier
      * Grenade strat = 6d6 MW on 4+ (replaces 1d6 S6 wound-roll model)
      * Look-Out-Sir allocation on target enumeration

    The pre-fix baseline was 100% Custodes then ~60% after the 2026-11-18
    fixpack; the correctness fixes land it at a roughly balanced ~50/50
    with the stock v2 lists — on a board the Tau kit can actually score.
    We pin a loose 30-70 band here so the test catches a future rules-
    drift regression without being brittle to rng-touching refactors.
    """
    custodes = sim.load_force(repo_root / "forces" / "force_custodes_2024cp_v2.yaml", catalog)
    tau = sim.load_force(repo_root / "forces" / "force_tau_2024cp_v2.yaml", catalog)
    board = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    blend = sim.simulate_many(custodes, tau, board, sims=500, rounds=5,
                              a_goes_first=True, seed=0)
    assert 0.30 <= blend["A"] <= 0.70, blend
    assert blend["A"] + blend["B"] + blend["draw"] == pytest.approx(1.0)
