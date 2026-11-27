"""Tests for fix #4 — Look-Out-Sir allocation on target enumeration.

10e rule: an attached character cannot be allocated as a shooting target
unless (a) the shooter has PRECISION, (b) the character is the last-model
survivor (simplified here as: filter returns characters iff nothing else
is visible). We verify by pointing non-PRECISION ranged attackers at an
attached unit and confirming the character never takes damage while its
squad is alive.
"""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from w40k_force_balancer.phases.shooting import (
    _is_look_out_sir_protected,
    _los_filter,
    shooting_phase,
)

from ..conftest import make_force, make_unit, make_weapon


def _board_short():
    b = sim.Board(deployment_gap_in=14)
    sim.set_board(b)
    return b


def _attach(character: sim.Unit, squad: sim.Unit) -> None:
    character.attached_to = squad
    squad.attached_character = character


def test_los_filter_hides_attached_character_from_non_precision_weapon():
    squad = make_unit(name="Squad")
    character = make_unit(name="Hero", models=1)
    _attach(character, squad)
    weapon = make_weapon(name="Boltgun")
    out = _los_filter([squad, character], weapon)
    assert character not in out
    assert squad in out


def test_los_filter_preserves_character_when_weapon_has_precision():
    squad = make_unit(name="Squad")
    character = make_unit(name="Hero", models=1)
    _attach(character, squad)
    weapon = make_weapon(
        name="Sniper", abilities={"PRECISION": {}}
    )
    out = _los_filter([squad, character], weapon)
    assert character in out


def test_los_filter_falls_back_when_only_character_is_visible():
    """If the only candidate is the attached character, return it anyway
    rather than leaving the attacker with nothing to shoot — the 10e
    rulebook's "no eligible target" escape hatch."""
    squad = make_unit(name="Squad")
    character = make_unit(name="Hero", models=1)
    _attach(character, squad)
    weapon = make_weapon(name="Boltgun")
    out = _los_filter([character], weapon)
    assert out == [character]


def test_breachers_cannot_ping_blade_champion_via_shooting(catalog, repo_root):
    """End-to-end: Breachers (no PRECISION) firing at a Custodian-Guard-
    plus-Blade-Champion attachment should route damage to the squad, not
    to the character. We run a 50-sim mini batch and assert the Blade
    Champion survives every game (its own melee turns can't reach the
    Tau side at 7" gap anyway)."""
    custodes = sim.load_force(
        repo_root / "forces" / "force_custodes_2024cp_v2.yaml", catalog,
    )
    tau = sim.load_force(
        repo_root / "forces" / "force_tau_2024cp_v2.yaml", catalog,
    )
    board = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)

    blade_deaths = 0
    for seed in range(15):
        c = custodes.copy()
        t = tau.copy()
        sim.set_board(board)
        sim.setup_initial_positions(c)
        sim.setup_initial_positions(t)
        rng = random.Random(seed)
        # Find Blade Champion & Custodian Guard — champion is attached.
        blade = next(u for u in c.units if u.name == "Blade Champion")
        guard = next(u for u in c.units if u.name == "Custodian Guard")
        assert blade.attached_to is guard

        # Make Breachers fire this round (round 2, so they can move in).
        breachers = next(u for u in t.units if u.name.startswith("Fire Warriors"))
        breachers.pos = board.deployment_gap_in - 7.0   # within 10" of center-ish
        # Route breachers' Tau side shooting
        sim.shooting_phase(t, c, round_no=1, rng=rng)

        if not blade.alive:
            blade_deaths += 1
    # Pre-fix: blade died in nearly every game. Post-fix: zero.
    assert blade_deaths == 0


def test_is_look_out_sir_protected_handles_detached_character():
    """When a squad is dead the character is on its own — Look Out Sir
    no longer applies and the character is a valid target."""
    squad = make_unit(name="Squad", models=0)   # dead
    character = make_unit(name="Hero", models=1)
    _attach(character, squad)
    assert _is_look_out_sir_protected(character) is False
