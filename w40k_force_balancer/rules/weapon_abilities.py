"""Weapon-ability resolution — the shot resolver.

`resolve_shots` orchestrates one weapon activation end-to-end, inlining
every weapon-ability check (Sustained/Lethal/Devastating/Twin-linked/
Torrent/Melta/Rapid Fire/Blast/Hazardous/Anti-X/Pistol/Heavy/Precision)
plus the defender-side modifiers (Stealth, Feel No Pain, invuln) at the
point where the roll happens.

STAT-APPROX flags on every expected-value shortcut; grep the file to audit.

STAT-APPROX ledger (applies to resolve_shots):
  * Devastating Wound damage does not get further FNP ignore rolls.

The independent-rolls save approximation that previously lived here was
fixed 2026-11-18 (upstream commit "fix: save rolls pick lower target"):
the save step now rolls once against the better (lower) of modified
armor and invuln.

Per-attack damage (finding #1, 2026-11-18): normal attacks each land on
one model; overkill when the model dies is discarded. Mortal wounds
(from Devastating Wounds) still pool-and-spill through the squad.

Precision per-hit Bernoulli (finding #6, 2026-11-18): each landed attack
with PRECISION independently flips 50/50 for Character vs Body
allocation. Previously allocated ceil(total/2) to Character, which
over-represented Precision by ~11pp for odd attack counts.

Wound-modifier cap (finding #9, 2026-11-18): symmetric clamp mirrors the
hit-modifier cap.
"""
from __future__ import annotations

import random

from ..core.dice import clamp, roll_d6, to_wound_threshold
from ..core.model import Force, Unit, Weapon
from .damage import ShotResult
from .unit_abilities import best_fnp


def resolve_shots(
    attacker: Unit,
    weapon: Weapon,
    target: Unit,
    distance: float,
    attacker_force: "Force",
    rng: random.Random,
    allow_crit_hit_bonus: bool = True,
    marker_rerolls: str | None = None,
) -> ShotResult:
    """Resolve one activation of a weapon by `attacker` against `target`.

    Returns a `ShotResult` carrying per-attack damage lists (body + char)
    plus mortal pools and self-mortals from Hazardous backlash. The result
    still tuple-unpacks as `(body_damage, char_damage, self_mortals)` for
    legacy callers.

    `marker_rerolls`: optional markerlight re-roll gate on the attacker's
    hit step. `"all_fails"` lets each missed hit re-roll once (= 2+
    markers); `"ones"` re-rolls only raw 1s (= 1 marker); `None` is the
    default no-reroll path.
    """
    if not weapon.melee:
        # Range gate: can only shoot if within weapon range.
        if distance > weapon.range_in:
            return ShotResult()

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
        return ShotResult()

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

    def _roll_one_hit(initial: int) -> tuple[int, int, int]:
        """Score one hit attempt. Returns (hits_delta, crit_delta, hazardous_delta)."""
        hits_d = 0
        crit_d = 0
        haz_d = 0
        if initial == 1 and hazardous:
            haz_d = 1
        if initial == 1:
            return hits_d, crit_d, haz_d
        if initial == 6:
            crit_d = 1
            hits_d = 1
        elif initial >= effective_hit:
            hits_d = 1
        return hits_d, crit_d, haz_d

    if torrent:
        hits = total_shots
        crit_hits = 0
    else:
        for _ in range(total_shots):
            raw = roll_d6(rng)
            h, c, haz = _roll_one_hit(raw)
            hits += h
            crit_hits += c
            hazardous_mortals += haz
            # Markerlight re-roll gate (fix #3). Applies to missed rolls
            # only; passes get no re-roll. For "ones", only raw 1s re-roll.
            # 11e: modifiers apply BEFORE the re-roll decision, so a raw 1
            # that is a "miss" is eligible for the ones-only re-roll; a
            # raw hit that becomes a miss via -1 modifier is eligible for
            # the all-fails re-roll but not the ones-only re-roll.
            missed = (h == 0)
            if missed and marker_rerolls:
                eligible = (
                    marker_rerolls == "all_fails"
                    or (marker_rerolls == "ones" and raw == 1)
                )
                if eligible:
                    raw2 = roll_d6(rng)
                    h2, c2, haz2 = _roll_one_hit(raw2)
                    hits += h2
                    crit_hits += c2
                    # Hazardous backlash does NOT re-trigger on the re-roll's 1
                    # — 11e Hazardous looks at the FINAL unmodified roll; the
                    # re-roll replaces the original, so we only count the
                    # re-roll's hazard flag.
                    hazardous_mortals = hazardous_mortals - haz + haz2

    # Sustained Hits: crit hits add n additional auto-hits
    if sustained and allow_crit_hit_bonus:
        hits += crit_hits * int(sustained.get("n", 1))

    # Lethal Hits: crit hits become auto-wounds, removed from the hit pool
    if lethal_hits and not torrent:
        lethal_autowounds = crit_hits
        hits -= crit_hits   # those hits bypass to-wound

    if hits <= 0 and lethal_autowounds <= 0:
        return ShotResult(self_mortals=hazardous_mortals)

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
    # Wound-modifier cap (finding #9): symmetric +/- 1 cap matching hit cap.
    wound_mod = clamp(wound_mod, -1, 1)
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
        return ShotResult(self_mortals=hazardous_mortals)

    # --- Devastating Wounds split (bypass save + FNP) ---------------------
    devastating_wounds = crit_wounds if devastating else 0
    normal_wounds = wounds - devastating_wounds

    # --- Save step for the normal wounds ---------------------------------
    unsaved = 0
    modified_save = target.save + weapon.ap
    inv = target.inv_save
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

    # Per-attack FNP (fix #1): each unsaved attack rolls its own FNP dice,
    # one per wound point, and the surviving damage lands on a single
    # model. Overkill when the model dies is lost.
    fnp = best_fnp(target)
    precision = (
        "PRECISION" in weapon.abilities and target.attached_character is not None
    )

    result = ShotResult(self_mortals=hazardous_mortals)

    for _ in range(unsaved):
        dmg = damage_per
        if fnp is not None and dmg > 0:
            ignored = sum(1 for _ in range(dmg) if roll_d6(rng) >= fnp)
            dmg = max(0, dmg - ignored)
        if dmg <= 0:
            continue
        # Precision per-hit Bernoulli (fix #6): each surviving attack
        # independently allocates to Character 50% of the time.
        if precision and roll_d6(rng) >= 4:
            result.char_attacks.append(dmg)
        else:
            result.body_attacks.append(dmg)

    # Devastating-Wound mortals: pooled, spill. Precision also directs
    # mortals — each dev-wound mortal independently rolls 50/50 for char.
    if devastating_wounds > 0:
        dw_damage_per = weapon.damage   # dev wounds use base damage (sim policy)
        for _ in range(devastating_wounds):
            if precision and roll_d6(rng) >= 4:
                result.mortal_char += dw_damage_per
            else:
                result.mortal_body += dw_damage_per

    return result
