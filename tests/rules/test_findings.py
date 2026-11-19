"""Regression tests for the 2026-11-18 adversarial-review findings.

Each test pins the fixed behavior from the review doc (PR #1). If a
future refactor collapses per-attack damage back into a pool, or drops
one of the gated mechanics, these tests should fail loudly.
"""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


# =========================================================================== #
# Finding #2 — Deep-Strike reserves count as alive
# =========================================================================== #


def test_finding2_force_with_only_reserves_is_still_alive(board_default):
    """Force.alive must return True while any unit is in reserves, even
    if every on-board unit is dead. Otherwise the reserved unit never
    gets to land."""
    onboard = make_unit(name="OnBoard", models=0)
    onboard.models = 0  # already dead
    reserve = make_unit(name="Reserve", models=3)
    reserve.in_reserves = True
    force = make_force("F", onboard, reserve)
    assert force.alive is True
    assert force.has_board_presence() is False
    # And reserves count toward total_wounds for the tiebreak.
    assert force.total_wounds > 0
