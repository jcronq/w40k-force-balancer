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


def test_sim_many_v2_custodes_still_favored(catalog, repo_root):
    """500-sim blend on shipped v2 forces, Custodes-first, seed=0.

    Baseline re-pinned 2026-11-18 after adversarial-review fixes (findings
    #1 per-attack damage, #3 markerlight re-roll, #5 Fall Back). The pre-
    fix baseline was 100% Custodes; the fixes narrow that but Custodes
    still win the clear majority — pin a floor of 60% here so the test
    catches a future rules-drift regression without being brittle to
    rng-touching refactors.
    """
    custodes = sim.load_force(repo_root / "force_custodes_2024cp_v2.yaml", catalog)
    tau = sim.load_force(repo_root / "force_tau_2024cp_v2.yaml", catalog)
    board = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    blend = sim.simulate_many(custodes, tau, board, sims=500, rounds=5,
                              a_goes_first=True, seed=0)
    assert blend["A"] >= 0.60, blend
    assert blend["A"] + blend["B"] + blend["draw"] == pytest.approx(1.0)
