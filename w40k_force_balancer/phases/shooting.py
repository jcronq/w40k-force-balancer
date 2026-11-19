"""Shooting phase — ranged activations, Grenade strat, Markerlight / Mont'ka."""
from __future__ import annotations

import random
from dataclasses import replace

from ..core import board as _board
from ..core.dice import roll_d6
from ..core.model import Force, Unit, Weapon
from ..rules.damage import apply_damage_with_attachment, apply_self_mortals_rng
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


def shooting_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
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
            _shoot_weapon_set(unit, pistol_weapons, current, enemy, round_no, rng, verbose)
            continue

        # Grenade stratagem — simple trigger: if a single INFANTRY enemy within
        # 8" and this unit has GRENADES keyword, consider throwing.
        if (
            "GRENADES" in unit.keywords
            and unit.has_keyword("INFANTRY")
            and _can_use_strat(current, "GRENADE", round_no)
        ):
            target = _board.closest_enemy_within(unit, enemy, 8)
            if target is not None and target.has_keyword("INFANTRY"):
                _spend_strat(current, "GRENADE", round_no, unit)
                # Grenade = 1d6 S6 AP-1 D1 attacks. Sampled once per use so
                # variance lands in the win/lose distribution; expected value
                # is 3.5. Fired from a single-model "virtual thrower" so
                # attacks do NOT multiply by the squad's model count.
                grenade_attacks = roll_d6(rng)
                virtual = Weapon(
                    name="Grenade (strat)", attacks=grenade_attacks, skill=4, strength=6,
                    ap=1, damage=1, melee=False, range_in=8,
                )
                ephemeral_thrower = replace(
                    unit,
                    models=1,
                    weapons=[virtual],
                    remained_stationary=unit.remained_stationary,
                )
                dist = _board.pair_distance(unit, target)
                shot = resolve_shots(ephemeral_thrower, virtual, target, dist, current, rng)
                deaths = apply_damage_with_attachment(target, shot, None, current, enemy)
                for d in deaths:
                    apply_deadly_demise(d, current, rng)
                if verbose:
                    print(f"    [{current.name}] GRENADE strat vs {target.name} -> {shot.body_damage}+{shot.char_damage} dmg")

        _shoot_weapon_set(
            unit,
            [w for w in unit.weapons if not w.melee],
            current, enemy, round_no, rng, verbose,
        )

        # Mont'ka — fire again
        if current.montka_target is unit:
            _shoot_weapon_set(
                unit,
                [w for w in unit.weapons if not w.melee],
                current, enemy, round_no, rng, verbose,
            )
            if verbose:
                print(f"    [{current.name}] Mont'ka: {unit.name} fires again")


def _shoot_weapon_set(
    unit: Unit,
    weapons: list[Weapon],
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool,
) -> None:
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
            if verbose:
                print(f"    [{current.name}] {unit.name} places {placed} markerlight(s) on {target.name}")
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

        shot = resolve_shots(unit, weapon, target, dist, current, rng,
                             marker_rerolls=marker_rerolls)
        if shot.self_mortals:
            # Hazardous backlash (fix #7): routed through best_fnp before
            # drain. Previously bypassed FNP entirely.
            apply_self_mortals_rng(unit, shot.self_mortals, rng)

        deaths = apply_damage_with_attachment(target, shot, None, current, enemy)
        for d in deaths:
            apply_deadly_demise(d, current, rng)
        if verbose and (shot.body_damage or shot.char_damage):
            print(f"    [{current.name}] {unit.name} {weapon.name} -> {target.name} dmg={shot.body_damage}+{shot.char_damage}")
