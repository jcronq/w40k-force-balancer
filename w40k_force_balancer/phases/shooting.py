"""Shooting phase — ranged activations, Grenade strat, Markerlight / Mont'ka."""
from __future__ import annotations

import random
from dataclasses import replace

from ..core import board as _board
from ..core.dice import roll_d6
from ..core.model import Force, Unit, Weapon
from ..engine.logger import BattleLogger, NullLogger, VerboseStdoutLogger
from ..rules.damage import (
    ShotResult,
    apply_damage_with_attachment,
    apply_self_mortals_rng,
)
from ..rules.stratagems import _can_use_strat, _spend_strat
from ..rules.unit_abilities import apply_deadly_demise
from ..rules.weapon_abilities import resolve_shots


def _threat_value(u: Unit) -> int:
    """Unit threat score: sum(A * D) across weapons * current models.
    Higher is scarier. Used by `highest_threat_value` target priority.
    """
    weapon_power = sum(max(1, w.attacks) * max(1, w.damage) for w in u.weapons)
    return weapon_power * max(1, u.models)


def _pick_target(candidates: list[Unit], shooter: Unit, priority: str) -> Unit:
    """Apply the shooter's doctrine target priority to a candidate list."""
    if priority == "closest_threat":
        return min(candidates, key=lambda e: _board.pair_distance(shooter, e))
    if priority == "highest_threat_value":
        # Max threat; tie-break to closest-first so engine remains deterministic.
        return max(
            candidates,
            key=lambda e: (_threat_value(e), -_board.pair_distance(shooter, e)),
        )
    # lowest_wounds (default engine behaviour, closest-to-dying)
    return min(candidates, key=lambda e: e.total_wounds)


def _attached_wounds(u: Unit) -> int:
    ac = u.attached_character
    if ac is None or not ac.alive:
        return 0
    return ac.total_wounds


def _is_look_out_sir_protected(e: Unit) -> bool:
    """10e Look Out Sir: an attached CHARACTER cannot be targeted while its
    bodyguard squad is still alive, unless the shooting weapon has PRECISION
    (handled by the caller).

    We treat a unit as protected iff its `attached_to` points at a still-
    living squad — matches how `apply_damage_with_attachment` routes damage.
    """
    return e.attached_to is not None and e.attached_to.alive


def _los_filter(
    candidates: list[Unit],
    weapon: Weapon | None,
) -> list[Unit]:
    """Fix #4 — enforce Look Out Sir on target enumeration.

    Removes attached characters from the candidate list unless the weapon
    carries PRECISION. If the filter would leave the shooter with zero
    targets (the character is the only visible enemy), fall back to the
    unfiltered list — that mirrors the "last-model exception" in a
    simplified form.
    """
    if weapon is not None and "PRECISION" in weapon.abilities:
        return candidates
    filtered = [e for e in candidates if not _is_look_out_sir_protected(e)]
    return filtered if filtered else candidates


def _emit_activation(
    logger: BattleLogger,
    round_no: int,
    turn_side: str,
    phase: str,
    unit: Unit,
    target: Unit,
    weapon: Weapon,
    shot,
    pre_models: int,
    pre_attached_wounds: int,
) -> None:
    body_dmg = shot.body_damage
    char_dmg = shot.char_damage
    # Attached-character damage: difference in attached_character wound pool.
    post_attached = _attached_wounds(target)
    # If the squad wiped and the character detached, apply_damage_with_attachment
    # moves the character off `target.attached_character`. Use char_dmg (the
    # shot's precision + spill output) as the authoritative delta.
    attached_delta = pre_attached_wounds - post_attached
    if attached_delta < 0:
        attached_delta = char_dmg
    models_killed = max(0, pre_models - target.models)
    logger.record({
        "round": round_no,
        "turn": turn_side,
        "phase": phase,
        "type": "activation",
        "actor": unit.name,
        "target": target.name,
        "weapon": weapon.name + (" (melee)" if weapon.melee else " (ranged)"),
        "attacks": shot.total_attacks,
        "hits": shot.hit_count,
        "wounds": shot.wound_count,
        "unsaved": shot.unsaved_count,
        "damage": body_dmg + char_dmg,
        "models_killed": models_killed,
        "attached_character_damage": attached_delta,
    })


def _emit_deaths(
    logger: BattleLogger,
    round_no: int,
    turn_side: str,
    phase: str,
    deaths: list[Unit],
) -> None:
    for d in deaths:
        logger.record({
            "round": round_no,
            "turn": turn_side,
            "phase": phase,
            "type": "unit_destroyed",
            "actor": d.name,
        })


def shooting_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
    logger: BattleLogger | None = None,
    turn_side: str = "A",
) -> None:
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()
    current.used_strats_this_phase = set()

    # Collect deaths to trigger Deadly Demise AFTER a given weapon activation.
    for unit in list(current.units):
        if not unit.alive or unit.in_reserves:
            continue
        if unit.advanced_this_turn:
            # Can't shoot after advancing (ignore Assault weapons for sim simplicity).
            continue
        if unit.engaged_with:
            # Can only fire Pistols in melee.
            pistol_weapons = [w for w in unit.weapons if "PISTOL" in w.abilities]
            if not pistol_weapons:
                continue
            _shoot_weapon_set(
                unit, pistol_weapons, current, enemy, round_no, rng,
                logger=logger, turn_side=turn_side,
            )
            continue

        # Grenade stratagem — 10e wording (fix #3):
        #   "Pick one enemy INFANTRY unit within 8" of a friendly INFANTRY
        #    unit with the GRENADES keyword, then roll six D6: for each
        #    4+ the target unit takes 1 mortal wound. Costs 1 CP, once per
        #    battle round per player."
        # Mortal wounds bypass armor + invuln (we route via
        # ShotResult.mortal_body -> apply_damage_to_squad).
        if (
            "GRENADES" in unit.keywords
            and unit.has_keyword("INFANTRY")
            and _can_use_strat(current, "GRENADE", round_no)
        ):
            # Grenade is non-PRECISION, so attached characters are LoS-protected.
            grenade_candidates = _los_filter(
                [
                    e for e in enemy.living_on_board()
                    if _board.pair_distance(unit, e) <= 8
                    and e.has_keyword("INFANTRY")
                ],
                weapon=None,
            )
            target = (
                min(grenade_candidates, key=lambda e: _board.pair_distance(unit, e))
                if grenade_candidates else None
            )
            if target is not None and target.has_keyword("INFANTRY"):
                _spend_strat(current, "GRENADE", round_no, unit)
                logger.record({
                    "round": round_no,
                    "turn": turn_side,
                    "phase": "shooting",
                    "type": "strat_used",
                    "strat_id": "GRENADE",
                    "actor": unit.name,
                })
                # Roll 6 d6; each 4+ deals 1 mortal wound.
                hits = sum(1 for _ in range(6) if roll_d6(rng) >= 4)
                pre_models = target.models
                pre_ac = _attached_wounds(target)
                shot = ShotResult(
                    mortal_body=hits,
                    total_attacks=6,
                    hit_count=hits,
                    wound_count=hits,
                    unsaved_count=hits,
                )
                deaths = apply_damage_with_attachment(
                    target, shot, None, current, enemy,
                )
                for d in deaths:
                    apply_deadly_demise(d, current, rng)
                # Log via a virtual weapon so the markdown renderer has a
                # name to display.
                virtual = Weapon(
                    name="Grenade (strat, 6d6 MW on 4+)",
                    attacks=6, skill=4, strength=0,
                    ap=0, damage=1, melee=False, range_in=8,
                )
                _emit_activation(logger, round_no, turn_side, "shooting",
                                 unit, target, virtual, shot, pre_models, pre_ac)
                _emit_deaths(logger, round_no, turn_side, "shooting", deaths)

        _shoot_weapon_set(
            unit,
            [w for w in unit.weapons if not w.melee],
            current, enemy, round_no, rng,
            logger=logger, turn_side=turn_side,
        )

        # Mont'ka — fire again
        if current.montka_target is unit:
            _shoot_weapon_set(
                unit,
                [w for w in unit.weapons if not w.melee],
                current, enemy, round_no, rng,
                logger=logger, turn_side=turn_side,
                montka_second_shot=True,
            )


def _shoot_weapon_set(
    unit: Unit,
    weapons: list[Weapon],
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool | None = None,
    logger: BattleLogger | None = None,
    turn_side: str = "A",
    montka_second_shot: bool = False,
) -> None:
    # Back-compat shim: older callers (tests) pass `verbose` as 7th positional
    # arg. If present, build a logger if none supplied.
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()
    if not weapons:
        return
    # Markerlight support: if this unit has MARKERLIGHT ability, allocate 1
    # shot per model from its first weapon (statistical approx) to markers
    # instead of damage.
    marker_ability = unit.abilities.get("MARKERLIGHT")
    if marker_ability is not None:
        target = _board.closest_enemy(unit, enemy)
        if target is not None:
            n_marks_rolls = unit.models  # one shot per model
            placed = sum(1 for _ in range(n_marks_rolls) if roll_d6(rng) >= 4)
            # Cap at 3
            key = id(target)
            current.markerlights[key] = min(3, current.markerlights.get(key, 0) + placed)
            # First weapon loses 1 shot per model to the markerlight.
            # STAT-APPROX: we fire first weapon with shots reduced by `models`.
            weapons = list(weapons)
            if weapons:
                weapons[0] = replace(weapons[0], attacks=max(0, weapons[0].attacks - 1))

    # Each weapon picks its own target per the firing unit's doctrine.
    priority = unit.doctrine.shooting.target_priority
    for weapon in weapons:
        candidates = [
            e for e in enemy.living_on_board()
            if _board.pair_distance(unit, e) <= weapon.range_in
        ]
        # Fix #4: Look Out Sir — can't target an attached character unless
        # the weapon has PRECISION.
        candidates = _los_filter(candidates, weapon)
        if not candidates:
            continue
        target = _pick_target(candidates, unit, priority)
        dist = _board.pair_distance(unit, target)
        # Markerlight re-roll gate (fix #3): no more BS patching. Instead
        # pass a `marker_rerolls` directive into resolve_shots so the hit
        # loop re-rolls after the modifier cap applies.
        marks = current.markerlights.get(id(target), 0)
        marker_rerolls = None
        if not weapon.melee and current.faction == "TAU_EMPIRE":
            if marks >= 2:
                marker_rerolls = "all_fails"
            elif marks == 1:
                marker_rerolls = "ones"

        pre_models = target.models
        pre_ac = _attached_wounds(target)
        shot = resolve_shots(unit, weapon, target, dist, current, rng,
                             marker_rerolls=marker_rerolls)
        if shot.self_mortals:
            # Hazardous backlash (fix #7): routed through best_fnp before
            # drain. Previously bypassed FNP entirely.
            apply_self_mortals_rng(unit, shot.self_mortals, rng)

        deaths = apply_damage_with_attachment(target, shot, None, current, enemy)
        for d in deaths:
            apply_deadly_demise(d, current, rng)
        _emit_activation(logger, round_no, turn_side,
                         "shooting", unit, target, weapon, shot, pre_models, pre_ac)
        _emit_deaths(logger, round_no, turn_side, "shooting", deaths)
