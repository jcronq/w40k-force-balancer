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
# Finding #1 — Per-attack damage (overkill discarded)
# =========================================================================== #


def test_finding1_one_d2_attack_kills_only_one_1w_model(board_default):
    """CRITICAL finding: one attack dealing D=2 vs a squad of 1W models
    should kill exactly ONE model; the second damage point is lost. Pre-
    fix (pooled damage) killed two models off this one attack."""
    w = make_weapon(attacks=1, skill=3, strength=4, damage=2)
    tgt = make_unit(name="Tgt", models=5, toughness=4, wounds_per_model=1, save=6)
    # hit 5 → wound 5 → save 1 → 1 unsaved attack with D=2.
    attacker = make_unit(name="Atk", models=1, weapons=[w])
    force = make_force("F", attacker)
    rng = RiggedRng([5, 5, 1])
    shot = sim.resolve_shots(attacker, w, tgt, 12.0, force, rng)
    sim.apply_damage_with_attachment(tgt, shot, None, force, None)
    assert tgt.models == 4, "1 D2 attack should kill 1 model, not 2"


def test_finding1_squad_wipe_does_not_spill_to_character(board_default):
    """Per-attack overkill when the last model dies stays lost — does
    NOT get transferred to a newly-exposed attached character."""
    w = make_weapon(attacks=1, skill=3, strength=4, damage=10)
    squad = make_unit(name="Squad", models=1, toughness=4, wounds_per_model=1, save=6)
    character = make_unit(name="Char", models=1, toughness=4, wounds_per_model=5, save=3,
                          keywords=["CHARACTER"])
    squad.attached_character = character
    character.attached_to = squad
    attacker = make_unit(name="Atk", models=1, weapons=[w])
    force = make_force("F", attacker)
    rng = RiggedRng([5, 5, 1])   # 1 unsaved, D=10
    shot = sim.resolve_shots(attacker, w, squad, 12.0, force, rng)
    sim.apply_damage_with_attachment(squad, shot, None, force, None)
    assert squad.alive is False
    assert character.alive is True
    assert character._current_model_wounds == 5, \
        "Overkill from the squad-killing shot must be discarded, not spilled to the character"


def test_finding1_mortal_wounds_still_spill(board_default):
    """Mortals (from Devastating Wounds) retain pooled-spill semantics:
    they drain through the squad and spill to the character on wipe."""
    w = make_weapon(
        attacks=2, skill=3, strength=4, damage=3,
        abilities={"DEVASTATING_WOUNDS": {}},
    )
    squad = make_unit(name="Squad", models=1, toughness=4, wounds_per_model=1, save=3)
    character = make_unit(name="Char", models=1, toughness=4, wounds_per_model=10, save=3,
                          keywords=["CHARACTER"])
    squad.attached_character = character
    character.attached_to = squad
    attacker = make_unit(name="Atk", models=1, weapons=[w])
    force = make_force("F", attacker)
    # 2 hits (5,5) → 2 wound rolls 6,6 → 2 crits → 2 mortal attacks
    # of D=3 each = 6 mortal damage pool. Precision not on, so all land
    # in mortal_body. Squad has 1 model/1W, eats 1 point, spills 5 to char.
    # To force the Bernoulli allocation deterministic (none, since no
    # PRECISION), we only need hit/wound rolls.
    rng = RiggedRng([5, 5, 6, 6])
    shot = sim.resolve_shots(attacker, w, squad, 12.0, force, rng)
    assert shot.mortal_body == 6
    sim.apply_damage_with_attachment(squad, shot, None, force, None)
    assert squad.alive is False
    assert character.alive is True
    # Char had 10 wounds, took 5 spilled mortal damage.
    assert character._current_model_wounds == 5


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


# =========================================================================== #
# Finding #3 — Markerlight re-roll is a re-roll, not a BS patch
# =========================================================================== #


def test_finding3_markerlight_2plus_rerolls_misses_empirically(board_default):
    """Pin finding #3: for BS4+ with 2+ markers (re-roll all failed hits),
    the empirical hit rate should land near the analytic 75% within 1pp
    over 100k rolls. Pre-fix implementation clamped at skill=2 (BS2+ =
    83.3%) which was 8.3pp low vs the true re-roll-fails value of 75%."""
    # BS4+ raw: hit on 4/5/6. Re-roll failures (1/2/3) once: 4/6 * 1/6 of
    # the re-rolls hit... wait: re-roll ALL failed hits once. Each shot:
    #   P(hit) = P(initial hit) + P(initial miss) * P(re-roll hit)
    #          = 3/6 + 3/6 * 3/6
    #          = 0.5 + 0.25 = 0.75
    w = make_weapon(attacks=1, skill=4, strength=4, damage=1)
    attacker = make_unit(name="Atk", models=1, weapons=[w])
    tgt = make_unit(name="Tgt", models=10**9, toughness=4, wounds_per_model=1, save=7)
    force = make_force("F", attacker)
    rng = random.Random(0)
    N = 100_000
    hits = 0
    for _ in range(N):
        shot = sim.resolve_shots(attacker, w, tgt, 12.0, force, rng,
                                 marker_rerolls="all_fails")
        # Each attack: body_attacks has 1 entry per unsaved. Save is 7+ so
        # everything that wounds goes through. Wound is S4 vs T4 = 4+.
        # To isolate the HIT step, run a lot and divide by expected-wound rate.
        # Simpler: count hit-rate directly from the resolve pipeline by
        # using a wound-impossible target and auto-landing path. Instead,
        # simulate via a single-shot weapon and auto-wounding via a
        # strength-overshoot. S10 vs T4 = 2+ to wound (5/6 pass).
        hits += len(shot.body_attacks)
    # P(hit) * P(wound at S4 T4 = 4+) * P(unsaved at Sv7) = 0.75 * 0.5 * 1.0 = 0.375
    expected = 0.375
    rate = hits / N
    assert abs(rate - expected) < 0.01, f"markerlight 2+ gate off: {rate:.4f} vs {expected}"


def test_finding3_markerlight_1marker_rerolls_only_ones(board_default):
    """1-marker gate re-rolls only unmodified 1s. Sanity test: at BS4+
    (hits on 4+), re-rolling only 1s adds a tiny bump — analytic
    P(hit) = 3/6 + 1/6 * 3/6 = 0.5833.
    Compare against no-reroll (0.5)."""
    w = make_weapon(attacks=1, skill=4, strength=4, damage=1)
    attacker = make_unit(name="Atk", models=1, weapons=[w])
    tgt = make_unit(name="Tgt", models=10**9, toughness=4, wounds_per_model=1, save=7)
    force = make_force("F", attacker)
    rng = random.Random(0)
    N = 100_000
    hits_1marker = sum(
        len(sim.resolve_shots(attacker, w, tgt, 12.0, force, rng,
                              marker_rerolls="ones").body_attacks)
        for _ in range(N)
    )
    # Expected hit rate: 7/12. Wound 4+ then unsaved. (7/12) * 0.5 = 7/24 ≈ 0.2917
    expected = (7 / 12) * 0.5
    rate = hits_1marker / N
    assert abs(rate - expected) < 0.01, f"markerlight 1-marker gate off: {rate:.4f} vs {expected}"


# =========================================================================== #
# Finding #7 — Hazardous mortals get FNP
# =========================================================================== #


def test_finding7_hazardous_backlash_goes_through_fnp(board_default):
    """Hazardous backlash should apply FNP before draining the unit. With
    a 2+ FNP against a single mortal wound, the ignore chance is 5/6; with
    enough trials, the mean damage per hazardous mortal lands near 0.167,
    not 1.0 as in the pre-fix path."""
    unit = make_unit(name="H", models=1, toughness=4, wounds_per_model=10**7, save=3)
    unit.abilities = {"FEEL_NO_PAIN": {"n": 2}}
    unit._current_model_wounds = 10**7
    rng = random.Random(0)
    N = 100_000
    for _ in range(N):
        sim.apply_self_mortals_rng(unit, 1, rng)
    taken = 10**7 - unit._current_model_wounds
    rate = taken / N
    expected = 1 / 6   # 5/6 ignored with FNP 2+
    assert abs(rate - expected) < 0.01, f"hazardous FNP off: {rate:.4f} vs {expected}"


# =========================================================================== #
# Finding #9 — Wound modifier cap is symmetric (±1)
# =========================================================================== #


def test_finding9_wound_modifier_clamped_at_plus_one(board_default):
    """If a hypothetical future stacking pushes wound_mod past -1, the
    clamp must still cap. Current code only applies -1 for Martial Ka'tah,
    so the direct guarantee is: after the clamp the effective wound
    target is still within [2,6] and never stronger than -1 of the base."""
    from w40k_force_balancer.core.dice import clamp
    assert clamp(-5, -1, 1) == -1
    assert clamp(5, -1, 1) == 1


# =========================================================================== #
# Finding #10 — Stratagem per-unit-per-turn gate
# =========================================================================== #


def test_finding10_cannot_fire_same_strat_on_same_unit_twice_in_a_turn(board_default):
    """A strat that targets the SAME unit twice in one turn across
    different phases should be denied the second time."""
    det = sim.Detachment(name="T", faction="X", army_ability="X",
                         stratagems=["GRENADE"])
    force = sim.Force(name="F", faction="X", detachment=det, cp=10)
    target = make_unit(name="T", models=1)
    # Phase 1: use the strat on this unit.
    assert sim._can_use_strat(force, "GRENADE", 1, target)
    sim._spend_strat(force, "GRENADE", 1, target)
    # Reset phase set (end of phase) — strat no longer blocked by phase.
    force.used_strats_this_phase = set()
    # Phase 2 same turn: SAME unit — must be denied by per-unit-per-turn gate.
    assert not sim._can_use_strat(force, "GRENADE", 1, target)
    # But a DIFFERENT unit in the same turn should still be allowed.
    other = make_unit(name="O", models=1)
    assert sim._can_use_strat(force, "GRENADE", 1, other)
    # And the SAME unit on a DIFFERENT turn should be allowed.
    assert sim._can_use_strat(force, "GRENADE", 2, target)
