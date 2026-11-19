"""Detachment-ability tests (section L)."""
from __future__ import annotations

import random

import pytest

import w40k_sim_v2 as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


# --- Martial Ka'tah (Shield Host) --------------------------------------- #

def test_martial_katah_declares_a_target_in_command_phase(catalog, board_default):
    det = catalog.detachments["shield_host"]
    custodes = make_unit(name="Custodian", models=1, toughness=6, wounds_per_model=3, save=2)
    enemy_unit = make_unit(name="Enemy", models=5, toughness=4, wounds_per_model=1, save=5)
    f = sim.Force(name="F", units=[custodes], detachment=det, cp=3)
    e = sim.Force(name="E", units=[enemy_unit])
    sim.command_phase(f, e, round_no=1, rng=random.Random(0))
    assert f.martial_katah_target is enemy_unit


def test_martial_katah_plus_one_to_wound_in_melee(catalog, board_default):
    """Rule: Custodes get +1 to wound rolls in melee vs the declared target."""
    det = catalog.detachments["shield_host"]
    # Attack: S4 vs T4 normally wounds on 4+. With katah, wounds on 3+.
    w = make_weapon(melee=True, attacks=1, skill=3, strength=4, damage=1)
    atk = make_unit(name="Custodian", models=1, weapons=[w])
    target = make_unit(name="Enemy", models=1, toughness=4, wounds_per_model=1, save=5)
    f = sim.Force(name="F", units=[atk], detachment=det, cp=3)
    f.martial_katah_target = target
    # Roll 3 on wound — without katah fails (needs 4+); with katah succeeds.
    body, _, _ = sim.resolve_shots(atk, w, target, 0.0, f, RiggedRng([5,  3,  1]))
    assert body == 1

    # Control: no katah declared.
    f2 = sim.Force(name="F2", units=[atk], detachment=det, cp=3)
    f2.martial_katah_target = None
    body2, _, _ = sim.resolve_shots(atk, w, target, 0.0, f2, RiggedRng([5,  3,  1]))
    assert body2 == 0


# --- Mont'ka (T'au) --------------------------------------------------- #

def test_montka_declares_shooting_target_in_command_phase(catalog, board_default):
    det = catalog.detachments["montka"]
    gunner = make_unit(name="Gunner", models=5,
                       weapons=[make_weapon(attacks=2, skill=4, strength=5,
                                            damage=1, range_in=24)])
    enemy_unit = make_unit(name="Enemy", models=5)
    f = sim.Force(name="F", units=[gunner], detachment=det, cp=3)
    e = sim.Force(name="E", units=[enemy_unit])
    sim.command_phase(f, e, round_no=1, rng=random.Random(0))
    assert f.montka_target is gunner


def test_montka_target_shoots_twice(catalog, board_default):
    """Rule: one T'au unit (declared in command phase) fires twice in shooting."""
    det = catalog.detachments["montka"]
    gun = make_weapon(attacks=1, skill=2, strength=10, damage=1, range_in=24)
    gunner = make_unit(name="Gunner", models=1, weapons=[gun])
    victim = make_unit(name="Victim", models=10, toughness=3, wounds_per_model=1, save=7)
    f = sim.Force(name="F", units=[gunner], detachment=det, cp=3, faction="TAU_EMPIRE")
    f.montka_target = gunner
    e = sim.Force(name="E", units=[victim])
    board = sim.Board(deployment_gap_in=24)
    sim._BOARD = board
    gunner.pos = 10.0; victim.pos = 10.0   # dist = 4
    # Two firings: each shoots 1 shot. Rig hits+wounds to succeed both times.
    # (First firing already consumes from the same rigged queue.)
    rng = RiggedRng([
        # first firing
        5,  5,
        # second firing (Mont'ka)
        5,  5,
    ])
    sim.shooting_phase(f, e, round_no=1, rng=rng)
    # Expected: 2 models dead (saves auto-fail at Sv7).
    assert victim.models == 8
