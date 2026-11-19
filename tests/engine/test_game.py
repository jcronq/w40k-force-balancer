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
    custodes = sim.load_force(repo_root / "force_custodes_2024cp_v2.yaml", catalog)
    tau = sim.load_force(repo_root / "force_tau_2024cp_v2.yaml", catalog)
    board = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    result = sim.simulate_game(custodes, tau, board, rounds=5, a_goes_first=True,
                               rng=random.Random(0))
    assert result in ("A", "B", "draw")


def test_sim_many_matches_v2_baseline(catalog, repo_root):
    """500-sim blend on shipped v2 forces, Custodes-first, seed=0 should return
    the pre-refactor outcome: Custodes dominate. Pinning the exact percentages
    lets a future refactor PR fail loud if combat semantics drift.

    Baseline captured 2026-11-18 (post-package-split):
        A goes first: {A:1.0, B:0.0, draw:0.0}  (Custodes sweep)
    """
    custodes = sim.load_force(repo_root / "force_custodes_2024cp_v2.yaml", catalog)
    tau = sim.load_force(repo_root / "force_tau_2024cp_v2.yaml", catalog)
    board = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    blend = sim.simulate_many(custodes, tau, board, sims=500, rounds=5,
                              a_goes_first=True, seed=0)
    # Under the shipped 2024 CP lists, Custodes dominate every trial.
    assert blend["A"] == pytest.approx(1.0)
    assert blend["B"] == pytest.approx(0.0)
    assert blend["draw"] == pytest.approx(0.0)
