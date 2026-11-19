"""Weapon-ability resolution — the shot resolver.

`resolve_shots` orchestrates one weapon activation end-to-end, inlining
every weapon-ability check (Sustained/Lethal/Devastating/Twin-linked/
Torrent/Melta/Rapid Fire/Blast/Hazardous/Anti-X/Pistol/Heavy/Precision)
plus the defender-side modifiers (Stealth, Feel No Pain, invuln) at the
point where the roll happens.

STAT-APPROX flags on every expected-value shortcut; grep the file to audit.

STAT-APPROX ledger (applies to resolve_shots):
  * Precision character allocation — when a Precision weapon targets a
    bodyguard squad with an attached character, exactly 50% of landed
    damage lands on the character directly (ceil(n/2)). Actual 40k lets
    the attacker allocate per-hit.
  * Devastating Wound damage does not get further FNP ignore rolls.

The independent-rolls save approximation that previously lived here was
fixed 2026-11-18 (upstream commit "fix: save rolls pick lower target"):
the save step now rolls once against the better (lower) of modified
armor and invuln.
"""
from __future__ import annotations

import random

from ..core.dice import clamp, roll_d6, to_wound_threshold
from ..core.model import Force, Unit, Weapon
from .unit_abilities import best_fnp


def resolve_shots(
    attacker: Unit,
    weapon: Weapon,
    target: Unit,
    distance: float,
    attacker_force: "Force",
    rng: random.Random,
    allow_crit_hit_bonus: bool = True,
) -> tuple[int, int, int]:
    """Resolve one activation of a weapon by `attacker` against `target`.

    Returns (damage_points_to_bodyguard, damage_points_to_character, self_mortals).
    `self_mortals` is Hazardous backlash from 1s on hit rolls.

    All weapon abilities + unit abilities are applied here.
    """
    if not weapon.melee:
        # Range gate: can only shoot if within weapon range.
        if distance > weapon.range_in:
            return (0, 0, 0)

    # --- Shot count -------------------------------------------------------
    total_shots = weapon.attacks * attacker.models
    # Blast: +1 attack per 5 full models in target unit.
    if "BLAST" in weapon.abilities:
        total_shots += weapon.attacks * (target.models // 5)
    # Rapid Fire: +N shots per model at half-range (ranged only).
    rf = weapon.abilities.get("RAPID_FIRE")
    if rf and not weapon.melee:
        half = weapon.range_in / 2.0
        if distance <= half:
            total_shots += int(rf.get("n", 1)) * attacker.models

    if total_shots <= 0:
        return (0, 0, 0)

    # --- Hit modifiers ----------------------------------------------------
    skill = weapon.skill
    modifiers = 0
    # Heavy: +1 to hit if stationary
    if "HEAVY" in weapon.abilities and attacker.remained_stationary:
        modifiers += 1
    # Stealth: -1 to incoming ranged hit rolls
    if not weapon.melee and target.has_ability("STEALTH"):
        modifiers -= 1
    # Modifier cap: +/-1 in 10e/11e.
    modifiers = clamp(modifiers, -1, 1)
    effective_hit = clamp(skill - modifiers, 2, 6)   # Lower target = easier.

    # --- Roll hits (with Torrent / Lethal Hits / Sustained Hits / Hazardous) --
    torrent = "TORRENT" in weapon.abilities
    lethal_hits = "LETHAL_HITS" in weapon.abilities
    sustained = weapon.abilities.get("SUSTAINED_HITS")
    hazardous = "HAZARDOUS" in weapon.abilities

    hits = 0
    crit_hits = 0        # unmodified 6s
    hazardous_mortals = 0
    lethal_autowounds = 0

    if torrent:
        hits = total_shots
        crit_hits = 0
    else:
        for _ in range(total_shots):
            raw = roll_d6(rng)
            if raw == 1 and hazardous:
                hazardous_mortals += 1
            # Unmodified 1 always misses; unmodified 6 always hits (crit).
            if raw == 1:
                continue
            if raw == 6:
                crit_hits += 1
                hits += 1
            elif raw >= effective_hit:
                hits += 1

    # Sustained Hits: crit hits add n additional auto-hits
    if sustained and allow_crit_hit_bonus:
        hits += crit_hits * int(sustained.get("n", 1))

    # Lethal Hits: crit hits become auto-wounds, removed from the hit pool
    if lethal_hits and not torrent:
        lethal_autowounds = crit_hits
        hits -= crit_hits   # those hits bypass to-wound

    if hits <= 0 and lethal_autowounds <= 0:
        return (0, 0, hazardous_mortals)

    # --- Wound step -------------------------------------------------------
    wound_th = to_wound_threshold(weapon.strength, target.toughness)
    # Anti-KEYWORD: if target has the keyword, wound-roll of N+ counts as crit
    # (= automatic wound AND triggers Devastating Wounds if present).
    anti_threshold = None
    for aid, params in weapon.abilities.items():
        if aid.startswith("ANTI_"):
            kw = params.get("keyword", aid.replace("ANTI_", ""))
            if target.has_keyword(kw):
                th = int(params.get("threshold", 4))
                anti_threshold = min(th, anti_threshold) if anti_threshold else th

    # Martial Ka'tah: +1 to wound in melee vs declared target
    wound_mod = 0
    if weapon.melee and attacker_force.martial_katah_target is target:
        wound_mod = -1  # LOWER target = easier
    wound_target = clamp(wound_th + wound_mod, 2, 6)

    twin_linked = "TWIN_LINKED" in weapon.abilities
    devastating = "DEVASTATING_WOUNDS" in weapon.abilities

    wounds = 0
    crit_wounds = 0
    for _ in range(hits):
        raw = roll_d6(rng)
        if raw == 6 or (anti_threshold is not None and raw >= anti_threshold):
            crit_wounds += 1
            wounds += 1
        elif raw >= wound_target:
            wounds += 1
        elif twin_linked:
            # Re-roll failed wound
            raw2 = roll_d6(rng)
            if raw2 == 6 or (anti_threshold is not None and raw2 >= anti_threshold):
                crit_wounds += 1
                wounds += 1
            elif raw2 >= wound_target:
                wounds += 1
    # Lethal auto-wounds skip to-wound entirely
    wounds += lethal_autowounds

    if wounds <= 0:
        return (0, 0, hazardous_mortals)

    # --- Devastating Wounds split (bypass save + FNP) ---------------------
    devastating_wounds = crit_wounds if devastating else 0
    normal_wounds = wounds - devastating_wounds

    # --- Save step for the normal wounds ---------------------------------
    # 40k rule: defender picks ONE save type — modified armor OR invulnerable,
    # whichever has the better (lower) target. Previously the sim rolled both
    # independently and passed on either, which inflates defensive durability
    # whenever AP makes the modified armor worse than the invuln. Bug fixed
    # 2026-11-18. Now picks the lower target and rolls once.
    unsaved = 0
    modified_save = target.save + weapon.ap
    inv = target.inv_save
    # Compute effective save target. Modified save that exceeds 6 means no
    # armor save available; fall back to inv if present, else guaranteed fail.
    armor_possible = modified_save <= 6
    if armor_possible and inv is not None:
        save_target = min(modified_save, inv)
    elif armor_possible:
        save_target = modified_save
    elif inv is not None:
        save_target = inv
    else:
        save_target = None  # no save possible; all wounds pass without rolling
    if save_target is None:
        unsaved = normal_wounds
    else:
        for _ in range(normal_wounds):
            if roll_d6(rng) < save_target:
                unsaved += 1

    # --- Damage calc for normal unsaved wounds ---------------------------
    damage_per = weapon.damage
    melta = weapon.abilities.get("MELTA")
    if melta and not weapon.melee:
        half = weapon.range_in / 2.0
        if distance <= half:
            damage_per += int(melta.get("n", 2))
    # Devastating wounds: `damage` mortals per crit, bypassing saves+FNP.
    mortal_damage_points = devastating_wounds * weapon.damage

    raw_damage = unsaved * damage_per

    # --- FNP (applied per wound point, not per unsaved-hit) --------------
    fnp = best_fnp(target)
    if fnp is not None and raw_damage > 0:
        ignored = sum(1 for _ in range(raw_damage) if roll_d6(rng) >= fnp)
        raw_damage = max(0, raw_damage - ignored)
    # Mortals from devastating wounds ignore FNP. (11th ed Dev Wounds are
    # mortal wounds now; some editions let FNP apply. We follow 11th:
    # mortals bypass FNP unless native unit has a specific anti-mortal FNP.
    # For sim simplicity, FNP does NOT apply to Devastating Wound mortals.)

    total_damage = raw_damage + mortal_damage_points

    # --- Precision: Character allocation ---------------------------------
    damage_character = 0
    damage_body = total_damage
    if "PRECISION" in weapon.abilities and target.attached_character is not None:
        # STAT-APPROX: 50% of total damage lands on the character directly,
        # bypassing Look Out Sir. Round half-up.
        damage_character = (total_damage + 1) // 2
        damage_body = total_damage - damage_character

    return (damage_body, damage_character, hazardous_mortals)
