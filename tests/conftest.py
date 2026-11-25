"""Shared test fixtures for the w40k_force_balancer suite."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import w40k_force_balancer as sim


@pytest.fixture
def catalog():
    return sim.load_catalog()


@pytest.fixture
def rng():
    return random.Random(0)


@pytest.fixture
def repo_root():
    """Repo root directory — force YAML examples live under `forces/`."""
    return REPO_ROOT


def make_weapon(**overrides) -> sim.Weapon:
    """Build a baseline Weapon. Pass abilities=dict(ID=params)."""
    defaults = dict(
        name="TestWeapon",
        attacks=1,
        skill=3,
        strength=4,
        ap=0,
        damage=1,
        melee=False,
        range_in=24,
        abilities={},
    )
    defaults.update(overrides)
    return sim.Weapon(**defaults)


def make_unit(**overrides) -> sim.Unit:
    defaults = dict(
        name="TestUnit",
        models=5,
        toughness=4,
        wounds_per_model=2,
        save=3,
        inv_save=None,
        fnp=None,
        movement=6,
        leadership=7,
        oc=1,
        keywords=["INFANTRY"],
        abilities={},
        weapons=[],
    )
    defaults.update(overrides)
    u = sim.Unit(**defaults)
    u.starting_models = u.models
    u._current_model_wounds = u.wounds_per_model
    return u


def make_force(name: str, *units: sim.Unit) -> sim.Force:
    return sim.Force(name=name, units=list(units))


@pytest.fixture
def board_default():
    b = sim.Board(width_in=44, height_in=30, deployment_gap_in=24)
    sim.set_board(b)
    return b


class RiggedRng:
    """Deterministic d6 roller — pops from queue. Falls back to 6 when exhausted."""
    def __init__(self, rolls: list[int], fallback: int = 6):
        self._rolls = list(rolls)
        self._fallback = fallback

    def randint(self, a: int, b: int) -> int:
        if self._rolls:
            return self._rolls.pop(0)
        return self._fallback


@pytest.fixture
def rigged():
    """Factory for RiggedRng. Call rigged([6, 6, 2, 5, ...])."""
    def make(rolls, fallback=6):
        return RiggedRng(rolls, fallback)
    return make
