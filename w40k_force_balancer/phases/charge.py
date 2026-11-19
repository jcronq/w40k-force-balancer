"""Charge phase — declare + roll + overwatch + Heroic Intervention."""
from __future__ import annotations

import random
from dataclasses import replace

from ..core import board as _board
from ..core.dice import roll_2d6
from ..core.model import Force, Unit
from ..rules.damage import apply_damage_with_attachment, apply_self_mortals_rng
from ..rules.stratagems import _can_use_strat, _spend_strat
from ..rules.unit_abilities import apply_deadly_demise
from ..rules.weapon_abilities import resolve_shots


def charge_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    current.used_strats_this_phase = set()
    for unit in current.units:
        if not unit.alive or unit.in_reserves:
            continue
        if unit.engaged_with:
            continue
        if unit.advanced_this_turn:
            # Can't charge after advancing (ignore Assault for sim).
            continue
        if unit.arrived_round == round_no and unit.has_ability("DEEP_STRIKE"):
            # Deep-struck this round: can't charge.
            continue
        # Doctrine gate: `never` skips the charge entirely.
        policy = unit.doctrine.charge.policy
        if policy == "never":
            continue
        # Pick target within 12" declaration range.
        target = _board.closest_enemy_within(unit, enemy, 12)
        if target is None:
            continue
        if policy == "conditional":
            # Only charge when we out-throw target melee count (symmetric with
            # the fall-back heuristic).
            my_attacks = sum(w.attacks * unit.models for w in unit.weapons if w.melee)
            their_attacks = sum(w.attacks * target.models for w in target.weapons if w.melee)
            if their_attacks >= my_attacks:
                continue
        dist = _board.pair_distance(unit, target)
        # Overwatch: target can fire. Uses Command strat or free-action? In 11e
        # it's a 1 CP strat. We model as the defender's FIRE_OVERWATCH strat
        # if they can afford it.
        _do_overwatch(unit, target, enemy, current, round_no, rng, verbose)
        if not unit.alive:
            continue
        if dist <= 0:
            unit.engaged_with.add(id(target))
            target.engaged_with.add(id(unit))
            continue
        roll = roll_2d6(rng)
        # Command re-roll if we have it and failed
        if roll < dist and _can_use_strat(current, "COMMAND_REROLL", round_no):
            _spend_strat(current, "COMMAND_REROLL", round_no)
            roll = max(roll, roll_2d6(rng))
        if roll >= dist:
            unit.pos += dist   # fully close
            unit.engaged_with.add(id(target))
            target.engaged_with.add(id(unit))
            if verbose:
                print(f"    [{current.name}] {unit.name} charges {target.name} (needed {dist:.0f}, rolled {roll})")
        else:
            if verbose:
                print(f"    [{current.name}] {unit.name} fails charge (needed {dist:.0f}, rolled {roll})")

    # Heroic Intervention — enemy units within 3" of a just-engaged defender
    # get a free 3" move into melee. Modelled per-unit on the enemy side at
    # end of charge phase.
    if _can_use_strat(enemy, "HEROIC_INTERVENTION", round_no) and enemy.cp >= 1:
        for defender in enemy.units:
            if not defender.alive or defender.in_reserves or defender.engaged_with:
                continue
            # Closest charging enemy within 3"?
            foe = _board.closest_enemy_within(defender, current, 3)
            if foe is not None:
                _spend_strat(enemy, "HEROIC_INTERVENTION", round_no)
                defender.pos += _board.pair_distance(defender, foe)
                defender.engaged_with.add(id(foe))
                foe.engaged_with.add(id(defender))
                if verbose:
                    print(f"    [{enemy.name}] Heroic Intervention: {defender.name} into {foe.name}")
                break


def _do_overwatch(
    charger: Unit,
    target: Unit,
    target_force: Force,
    charger_force: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool,
) -> None:
    if not _can_use_strat(target_force, "FIRE_OVERWATCH", round_no):
        return
    _spend_strat(target_force, "FIRE_OVERWATCH", round_no)
    dist = _board.pair_distance(charger, target)
    # Overwatch hits on 6+ (5+ with For the Greater Good).
    ow_skill = 5 if target.has_ability("FOR_THE_GREATER_GOOD") else 6
    # STAT-APPROX: we temporarily patch each weapon's BS to ow_skill and fire.
    for weapon in target.weapons:
        if weapon.melee or weapon.range_in < dist:
            continue
        patched = replace(weapon, skill=ow_skill)
        shot = resolve_shots(target, patched, charger, dist, target_force, rng)
        if shot.self_mortals:
            apply_self_mortals_rng(target, shot.self_mortals, rng)
        deaths = apply_damage_with_attachment(charger, shot, None, target_force, charger_force)
        for d in deaths:
            apply_deadly_demise(d, target_force, rng)
        if verbose and (shot.body_damage or shot.char_damage):
            print(f"    [{target_force.name}] OVERWATCH {target.name}->{charger.name} dmg={shot.body_damage}+{shot.char_damage}")
