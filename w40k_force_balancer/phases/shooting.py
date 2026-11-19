"""Shooting phase — ranged activations, Grenade strat, Markerlight / Mont'ka."""
from __future__ import annotations

import random
from dataclasses import replace

from ..core import board as _board
from ..core.dice import roll_d6
from ..core.model import Force, Unit, Weapon
from ..rules.damage import apply_damage_with_attachment, apply_self_mortals
from ..rules.stratagems import _can_use_strat, _spend_strat
from ..rules.unit_abilities import apply_deadly_demise
from ..rules.weapon_abilities import resolve_shots


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
                _spend_strat(current, "GRENADE", round_no)
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
                body, char, _ = resolve_shots(ephemeral_thrower, virtual, target, dist, current, rng)
                deaths = apply_damage_with_attachment(target, body, char, current, enemy)
                for d in deaths:
                    apply_deadly_demise(d, current, rng)
                if verbose:
                    print(f"    [{current.name}] GRENADE strat vs {target.name} -> {body}+{char} dmg")

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


def _resolve_markerlights(
    attacker: Unit,
    weapon: Weapon,
    current: Force,
    enemy: Force,
    rng: random.Random,
) -> None:
    """If the unit has MARKERLIGHT, dedicate 1 shot per model to placing
    markers on the closest enemy target before firing the rest. STAT-APPROX:
    uses expected-value increment (1 model = 1 shot = 0.5 marker on avg at 4+)."""
    # No-op scaffold — actual markerlight wiring happens in _shoot_weapon_set
    # when MARKERLIGHT unit fires. See markerlight integration below.
    pass


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

    # Each weapon picks its own target, closest-to-dying within range.
    for weapon in weapons:
        candidates = [
            e for e in enemy.living_on_board()
            if _board.pair_distance(unit, e) <= weapon.range_in
        ]
        if not candidates:
            continue
        target = min(candidates, key=lambda e: e.total_wounds)
        dist = _board.pair_distance(unit, target)
        # STAT-APPROX: markerlight hit-reroll — if 1+ markers on target and
        # T'au force, apply at-least-one-reroll on hit roll (modelled by
        # +0.5/6 bump to effective skill which is messy). Instead we bump the
        # effective hit skill by 1 if 2+ markers (re-roll all failed), or re-
        # roll 1s (-small bump) if 1 marker. Approximation applied by temp
        # patching weapon.skill.
        patched_weapon = weapon
        marks = current.markerlights.get(id(target), 0)
        if marks >= 2 and not weapon.melee and (current.faction == "TAU_EMPIRE"):
            patched_weapon = replace(weapon, skill=max(2, weapon.skill - 1))  # re-roll all fails ≈ -1 to skill target
        elif marks == 1 and not weapon.melee and (current.faction == "TAU_EMPIRE"):
            # Re-roll 1s -> small bump (~ -0.5 effective skill). We skip for simplicity.
            patched_weapon = weapon

        body, char, self_mortals = resolve_shots(unit, patched_weapon, target, dist, current, rng)
        if self_mortals:
            apply_self_mortals(unit, self_mortals)

        deaths = apply_damage_with_attachment(target, body, char, current, enemy)
        for d in deaths:
            apply_deadly_demise(d, current, rng)
        if verbose and (body or char):
            print(f"    [{current.name}] {unit.name} {weapon.name} -> {target.name} dmg={body}+{char}")
