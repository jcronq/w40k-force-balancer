"""Weapon-ability tests. One rule, one test, each on a known-state battlefield.

Every rule referenced in catalog/abilities.yaml with category=weapon must
have at least one test here demonstrating the expected mechanical effect.
"""
from __future__ import annotations

import random

import pytest

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit, make_force, RiggedRng


def _resolve(weapon, target, attacker=None, force=None, distance=12.0, rolls=None):
    atk = attacker or make_unit(name="Atk", models=1, weapons=[weapon])
    f = force or make_force("AtkForce", atk)
    rng = RiggedRng(rolls or [])
    return sim.resolve_shots(atk, weapon, target, distance, f, rng)


# --- Baseline sanity ----------------------------------------------------- #

def test_plain_shot_no_abilities(board_default):
    # 1 shot, BS3, S4, AP0, D1 vs T4/W1/Sv4, no abilities.
    # Hit roll 5 (>=3 hit), wound roll 5 (>=4 wound S==T), save roll 3 (fails vs Sv4 since 3<4).
    w = make_weapon(attacks=1, skill=3, strength=4, damage=1)
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=1, save=4)
    body, char, self_mortals = _resolve(w, tgt, rolls=[5, 5, 3])
    assert (body, char, self_mortals) == (1, 0, 0)


# --- Sustained Hits ------------------------------------------------------ #

def test_sustained_hits_adds_extra_hits_on_crit(board_default):
    """Rule: each 6-to-hit scores N additional auto-hits beyond the crit itself.
    Rolls: 1 shot, hit=6 => crit => 1 regular hit + SUSTAINED_HITS(2) additional = 3 hits.
    Then 3 wound rolls all 4+ succeed, 3 saves all fail => 3 damage."""
    w = make_weapon(
        attacks=1, skill=3, strength=4, damage=1,
        abilities={"SUSTAINED_HITS": {"n": 2}},
    )
    tgt = make_unit(name="Tgt", models=3, toughness=4, wounds_per_model=1, save=6)
    body, _, _ = _resolve(w, tgt, rolls=[6,  4, 4, 4,  1, 1, 1])
    assert body == 3


# --- Lethal Hits --------------------------------------------------------- #

def test_lethal_hits_skips_wound_roll(board_default):
    """Rule: 6-to-hit auto-wounds, skipping to-wound step.
    1 shot, hit=6 (crit). With LETHAL_HITS that's 1 auto-wound, no wound roll.
    Save=1 (fails vs Sv3 post AP0 since 1<3) => 1 damage."""
    w = make_weapon(
        attacks=1, skill=3, strength=4, damage=1,
        abilities={"LETHAL_HITS": {}},
    )
    tgt = make_unit(name="Tgt", models=1, toughness=10, wounds_per_model=1, save=3)
    # Note T=10 means normal S4 can't wound (needs 6+); lethal skips that step.
    body, _, _ = _resolve(w, tgt, rolls=[6,  1])
    assert body == 1


# --- Devastating Wounds -------------------------------------------------- #

def test_devastating_wounds_bypass_saves(board_default):
    """Rule: 6-to-wound becomes `damage` mortal wounds, bypass saves + FNP."""
    w = make_weapon(
        attacks=1, skill=3, strength=4, damage=2,
        abilities={"DEVASTATING_WOUNDS": {}},
    )
    # Sv2 would normally save; dev wounds bypass.
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=5, save=2)
    body, _, _ = _resolve(w, tgt, rolls=[5,  6])   # hit 5 (hit), wound 6 (crit)
    assert body == 2   # 2 mortals, no save


# --- Twin-linked --------------------------------------------------------- #

def test_twin_linked_rerolls_failed_wounds(board_default):
    """Rule: failed wound rolls get a re-roll.
    1 shot hits, wound roll 2 (fails vs 4+). Re-roll yields 6 (crit) => wound.
    Save 1 fails => 1 damage."""
    w = make_weapon(
        attacks=1, skill=3, strength=4, damage=1,
        abilities={"TWIN_LINKED": {}},
    )
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=1, save=3)
    body, _, _ = _resolve(w, tgt, rolls=[5,  2,  6,  1])
    assert body == 1


# --- Torrent ------------------------------------------------------------- #

def test_torrent_auto_hits(board_default):
    """Rule: skip the hit roll, every shot hits. 3 shots all hit.
    Wound rolls all 5 (succeed), save rolls all 1 (fail) => 3 damage."""
    w = make_weapon(
        attacks=3, skill=6, strength=4, damage=1,
        abilities={"TORRENT": {}},
    )
    tgt = make_unit(name="Tgt", models=3, toughness=4, wounds_per_model=1, save=3)
    # No hit rolls consumed. Three wounds, three saves.
    body, _, _ = _resolve(w, tgt, rolls=[5, 5, 5,  1, 1, 1])
    assert body == 3


# --- Melta --------------------------------------------------------------- #

def test_melta_bonus_damage_at_half_range(board_default):
    """Rule: +N damage within half-range.
    Range=12, distance=5 (within half=6). D2 + Melta(2) = 4 damage per unsaved."""
    w = make_weapon(
        attacks=1, skill=3, strength=8, damage=2, range_in=12,
        abilities={"MELTA": {"n": 2}},
    )
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=10, save=6)
    body, _, _ = _resolve(w, tgt, distance=5.0, rolls=[5,  5,  1])
    assert body == 4


def test_melta_no_bonus_outside_half_range(board_default):
    w = make_weapon(
        attacks=1, skill=3, strength=8, damage=2, range_in=12,
        abilities={"MELTA": {"n": 2}},
    )
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=10, save=6)
    body, _, _ = _resolve(w, tgt, distance=10.0, rolls=[5,  5,  1])
    assert body == 2


# --- Rapid Fire ---------------------------------------------------------- #

def test_rapid_fire_doubles_shots_at_half_range(board_default):
    """Rule: +N shots per model within half-range.
    Weapon A=1 + RF1, 1 model => 2 shots within half range. At full range => 1 shot."""
    attacker = make_unit(name="Atk", models=1)
    w = make_weapon(
        attacks=1, skill=3, strength=4, damage=1, range_in=24,
        abilities={"RAPID_FIRE": {"n": 1}},
    )
    attacker.weapons = [w]
    tgt = make_unit(name="Tgt", models=3, toughness=4, wounds_per_model=1, save=5)
    # within half range: 2 shots, both hit, wound, fail save => 2 damage
    body, _, _ = _resolve(w, tgt, attacker=attacker, distance=6.0,
                           rolls=[5, 5,  5, 5,  1, 1])
    assert body == 2


# --- Blast --------------------------------------------------------------- #

def test_blast_adds_shot_per_five_models(board_default):
    """Rule: +1 attack per full 5 models in target unit.
    Attacker=1 model, Weapon A=1 + Blast; Target has 10 models => 1 + 2 = 3 shots."""
    w = make_weapon(
        attacks=1, skill=3, strength=4, damage=1,
        abilities={"BLAST": {}},
    )
    tgt = make_unit(name="Tgt", models=10, toughness=4, wounds_per_model=1, save=5)
    # 3 shots -> 3 hits (5/5/5), 3 wounds (5/5/5), 3 saves fail (1/1/1) => 3 damage.
    body, _, _ = _resolve(w, tgt, rolls=[5, 5, 5,  5, 5, 5,  1, 1, 1])
    assert body == 3


# --- Hazardous ----------------------------------------------------------- #

def test_hazardous_self_mortal_on_hit_roll_of_1(board_default):
    """Rule: each unmodified 1-to-hit => bearer takes 1 mortal wound."""
    w = make_weapon(
        attacks=2, skill=3, strength=4, damage=1,
        abilities={"HAZARDOUS": {}},
    )
    tgt = make_unit(name="Tgt", models=3, toughness=4, wounds_per_model=1, save=6)
    # Hit rolls 1 and 1: zero hits, 2 self mortals.
    _, _, self_mortals = _resolve(w, tgt, rolls=[1, 1])
    assert self_mortals == 2


# --- Anti-KEYWORD -------------------------------------------------------- #

def test_anti_infantry_crits_on_lower_wound_threshold(board_default):
    """Rule: ANTI_INFANTRY 4+ makes wound rolls >=4 count as crits vs INFANTRY.
    Combined with DEV wounds, means more mortal-wound output vs INFANTRY."""
    w = make_weapon(
        attacks=1, skill=3, strength=3, damage=1,
        abilities={
            "ANTI_INFANTRY": {"keyword": "INFANTRY", "threshold": 4},
            "DEVASTATING_WOUNDS": {},
        },
    )
    tgt = make_unit(name="Tgt", models=1, toughness=6, wounds_per_model=5, save=2,
                    keywords=["INFANTRY"])
    # Hit 5 (hit), wound 4 (normally S3 vs T6 needs 6+ to wound, but Anti-Inf 4+
    # makes this a crit). Dev wounds => 1 mortal, bypassing Sv2.
    body, _, _ = _resolve(w, tgt, rolls=[5,  4])
    assert body == 1


# --- Pistol -------------------------------------------------------------- #

def test_pistol_fires_in_melee(board_default):
    """Rule: PISTOL weapons may fire in melee."""
    pistol = make_weapon(
        attacks=1, skill=3, strength=4, damage=1, range_in=12,
        abilities={"PISTOL": {}},
    )
    attacker = make_unit(name="Atk", models=1, weapons=[pistol])
    enemy = make_unit(name="Enemy", models=5, toughness=4, wounds_per_model=1, save=5)
    attacker.engaged_with.add(id(enemy))
    enemy.engaged_with.add(id(attacker))

    atk_force = make_force("AF", attacker)
    enemy_force = make_force("EF", enemy)
    # Minimal shooting_phase invocation: deploy them so pair_distance is 0.
    board = sim.Board()
    sim.set_board(board)
    attacker.pos = board.deployment_gap_in
    enemy.pos = 0.0

    rng = random.Random(1)
    sim.shooting_phase(atk_force, enemy_force, round_no=1, rng=rng)
    # Pistol should have fired. Can't assert deterministic damage without
    # mocking, but enemy took at least some damage probabilistically — do 50
    # runs and expect positive mean.
    hits = 0
    for seed in range(50):
        a2 = atk_force.copy()
        e2 = enemy_force.copy()
        a2.units[0].engaged_with.add(id(e2.units[0]))
        e2.units[0].engaged_with.add(id(a2.units[0]))
        a2.units[0].pos = board.deployment_gap_in
        e2.units[0].pos = 0.0
        sim.shooting_phase(a2, e2, 1, random.Random(seed))
        hits += 5 - e2.units[0].models
    assert hits > 0, "Pistol should fire in melee at least sometimes"


# --- Heavy --------------------------------------------------------------- #

def test_heavy_hit_bonus_when_stationary(board_default):
    """Rule: +1 to hit if bearer Remained Stationary."""
    attacker = make_unit(name="Atk", models=1)
    attacker.remained_stationary = True
    w = make_weapon(
        attacks=1, skill=4, strength=4, damage=1,
        abilities={"HEAVY": {}},
    )
    attacker.weapons = [w]
    tgt = make_unit(name="Tgt", models=1, toughness=4, wounds_per_model=1, save=6)
    # With Heavy + stationary, effective BS = 3+. Hit roll of 3 passes.
    body, _, _ = _resolve(w, tgt, attacker=attacker, rolls=[3,  5,  1])
    assert body == 1

    # Move: not stationary; roll 3 vs BS4 fails.
    attacker2 = make_unit(name="Atk", models=1, weapons=[w])
    attacker2.remained_stationary = False
    body2, _, _ = _resolve(w, tgt, attacker=attacker2, rolls=[3,  5,  1])
    assert body2 == 0


# --- Precision ----------------------------------------------------------- #

def test_precision_bernoulli_allocates_per_hit(board_default):
    """Rule (post-fix #6): each landed attack independently rolls 50/50 for
    character vs body. Deterministic with rigged Bernoulli rolls — 4,4,1,1
    means first two to char, last two to body.
    """
    w = make_weapon(
        attacks=4, skill=3, strength=4, damage=1,
        abilities={"PRECISION": {}},
    )
    character = make_unit(name="Char", models=1, toughness=4, wounds_per_model=3, save=3,
                           keywords=["INFANTRY", "CHARACTER"])
    squad = make_unit(name="Squad", models=4, toughness=4, wounds_per_model=1, save=4,
                      keywords=["INFANTRY"])
    squad.attached_character = character
    character.attached_to = squad
    # hits x4 / wounds x4 / saves x4 / Bernoulli x4 — 4,4,1,1 → 2 char, 2 body
    body, char, _ = _resolve(w, squad,
                             rolls=[5, 5, 5, 5,  5, 5, 5, 5,  1, 1, 1, 1,  4, 4, 1, 1])
    assert (body, char) == (2, 2)


def test_precision_empirical_rate_is_50pct(board_default):
    """Pin finding #6: Monte-Carlo the Bernoulli split and demand ~50%
    allocation to Character, within 1pp over 100k trials. Pre-fix used
    ceil(n/2) which overcounted by ~11pp on odd totals."""
    w = make_weapon(
        attacks=1, skill=2, strength=4, damage=1,
        abilities={"PRECISION": {}},
    )
    character = make_unit(name="Char", models=1, toughness=4, wounds_per_model=10**9, save=2,
                           keywords=["INFANTRY", "CHARACTER"])
    squad = make_unit(name="Squad", models=10**9, toughness=4, wounds_per_model=1, save=7,
                      keywords=["INFANTRY"])
    squad.attached_character = character
    character.attached_to = squad
    attacker = make_unit(name="Atk", models=1, weapons=[w])
    force = make_force("F", attacker)
    rng = random.Random(0)
    total_char = 0
    total_body = 0
    N = 100_000
    for _ in range(N):
        shot = sim.resolve_shots(attacker, w, squad, 12.0, force, rng)
        total_body += len(shot.body_attacks)
        total_char += len(shot.char_attacks)
    rate_char = total_char / (total_char + total_body)
    assert abs(rate_char - 0.5) < 0.01, f"Precision Bernoulli off: {rate_char:.4f}"
