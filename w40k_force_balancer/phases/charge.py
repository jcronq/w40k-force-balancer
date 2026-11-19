"""Charge phase — declare + roll + overwatch + Heroic Intervention."""
from __future__ import annotations

import random
from dataclasses import replace

from ..core import board as _board
from ..core.dice import roll_2d6
from ..core.model import Force, Unit
from ..engine.logger import BattleLogger, NullLogger, VerboseStdoutLogger
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
    logger: BattleLogger | None = None,
    turn_side: str = "A",
    enemy_side: str = "B",
) -> None:
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()
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
        _do_overwatch(unit, target, enemy, current, round_no, rng,
                      verbose=False, logger=logger, turn_side=turn_side,
                      enemy_side=enemy_side)
        if not unit.alive:
            continue
        if dist <= 0:
            unit.engaged_with.add(id(target))
            target.engaged_with.add(id(unit))
            logger.record({
                "round": round_no,
                "turn": turn_side,
                "phase": "charge",
                "type": "charge_connect",
                "actor": unit.name,
                "target": target.name,
            })
            continue
        roll = roll_2d6(rng)
        # Command re-roll if we have it and failed
        if roll < dist and _can_use_strat(current, "COMMAND_REROLL", round_no):
            _spend_strat(current, "COMMAND_REROLL", round_no)
            logger.record({
                "round": round_no,
                "turn": turn_side,
                "phase": "charge",
                "type": "strat_used",
                "strat_id": "COMMAND_REROLL",
                "actor": unit.name,
            })
            roll = max(roll, roll_2d6(rng))
        succeeded = roll >= dist
        if succeeded:
            unit.pos += dist   # fully close
            unit.engaged_with.add(id(target))
            target.engaged_with.add(id(unit))
        logger.record({
            "round": round_no,
            "turn": turn_side,
            "phase": "charge",
            "type": "charge_attempt",
            "actor": unit.name,
            "target": target.name,
            "distance": dist,
            "roll": roll,
            "succeeded": succeeded,
        })

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
                logger.record({
                    "round": round_no,
                    "turn": enemy_side,
                    "phase": "charge",
                    "type": "strat_used",
                    "strat_id": "HEROIC_INTERVENTION",
                    "actor": defender.name,
                })
                logger.record({
                    "round": round_no,
                    "turn": enemy_side,
                    "phase": "charge",
                    "type": "heroic_intervention",
                    "actor": defender.name,
                    "target": foe.name,
                })
                break


def _do_overwatch(
    charger: Unit,
    target: Unit,
    target_force: Force,
    charger_force: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
    logger: BattleLogger | None = None,
    turn_side: str = "A",
    enemy_side: str = "B",
) -> None:
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()
    if not _can_use_strat(target_force, "FIRE_OVERWATCH", round_no):
        return
    _spend_strat(target_force, "FIRE_OVERWATCH", round_no)
    logger.record({
        "round": round_no,
        "turn": enemy_side,
        "phase": "charge",
        "type": "strat_used",
        "strat_id": "FIRE_OVERWATCH",
        "actor": target.name,
    })
    dist = _board.pair_distance(charger, target)
    # Overwatch hits on 6+ (5+ with For the Greater Good).
    ow_skill = 5 if target.has_ability("FOR_THE_GREATER_GOOD") else 6
    # STAT-APPROX: we temporarily patch each weapon's BS to ow_skill and fire.
    for weapon in target.weapons:
        if weapon.melee or weapon.range_in < dist:
            continue
        patched = replace(weapon, skill=ow_skill)
        pre_models = charger.models
        pre_ac = (
            charger.attached_character.total_wounds
            if charger.attached_character and charger.attached_character.alive
            else 0
        )
        shot = resolve_shots(target, patched, charger, dist, target_force, rng)
        if shot.self_mortals:
            apply_self_mortals_rng(target, shot.self_mortals, rng)
        deaths = apply_damage_with_attachment(charger, shot, None, target_force, charger_force)
        for d in deaths:
            apply_deadly_demise(d, target_force, rng)
        logger.record({
            "round": round_no,
            "turn": enemy_side,
            "phase": "charge",
            "type": "activation",
            "actor": target.name,
            "target": charger.name,
            "weapon": weapon.name + " (overwatch)",
            "attacks": shot.total_attacks,
            "hits": shot.hit_count,
            "wounds": shot.wound_count,
            "unsaved": shot.unsaved_count,
            "damage": shot.body_damage + shot.char_damage,
            "models_killed": max(0, pre_models - charger.models),
            "attached_character_damage": max(
                0,
                pre_ac - (
                    charger.attached_character.total_wounds
                    if charger.attached_character and charger.attached_character.alive
                    else 0
                ),
            ),
        })
        for d in deaths:
            logger.record({
                "round": round_no,
                "turn": enemy_side,
                "phase": "charge",
                "type": "unit_destroyed",
                "actor": d.name,
            })
