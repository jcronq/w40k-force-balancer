"""Fight phase — Fights-First / Normal / Fights-Last tiers, alternating activations."""
from __future__ import annotations

import random

from ..core.model import Force, Unit
from ..engine.logger import BattleLogger, NullLogger, VerboseStdoutLogger
from ..rules.damage import apply_damage_with_attachment
from ..rules.unit_abilities import apply_deadly_demise
from ..rules.weapon_abilities import resolve_shots


def fight_phase(
    first_force: Force,
    second_force: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
    logger: BattleLogger | None = None,
    turn_side: str = "A",
    enemy_side: str = "B",
) -> None:
    """Resolve the Fight phase. Fights First tier, then Normal, then Fights
    Last. Within each tier, alternate activations starting with the player
    whose turn it is."""
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()
    tiers = ["first", "normal", "last"]

    def bucket(force: Force, tier: str) -> list[Unit]:
        out = []
        for u in force.units:
            if not u.alive or u.in_reserves or not u.engaged_with:
                continue
            if tier == "first":
                if u.has_ability("FIGHTS_FIRST"):
                    out.append(u)
            elif tier == "normal":
                if not u.has_ability("FIGHTS_FIRST") and not u.has_ability("FIGHTS_LAST"):
                    out.append(u)
            else:
                if u.has_ability("FIGHTS_LAST"):
                    out.append(u)
        return out

    for tier in tiers:
        queue_first = bucket(first_force, tier)
        queue_second = bucket(second_force, tier)
        # Alternate activations: first-player-first in 11e within a tier.
        while queue_first or queue_second:
            if queue_first:
                u = queue_first.pop(0)
                if u.alive and u.engaged_with:
                    _fight_activation(u, first_force, second_force,
                                      round_no, rng, logger, turn_side)
            if queue_second:
                u = queue_second.pop(0)
                if u.alive and u.engaged_with:
                    _fight_activation(u, second_force, first_force,
                                      round_no, rng, logger, enemy_side)


def _fight_activation(
    unit: Unit,
    unit_force: Force,
    enemy_force: Force,
    round_no: int,
    rng: random.Random,
    logger: BattleLogger | None = None,
    turn_side: str = "A",
    verbose: bool | None = None,
) -> None:
    # Back-compat shim: older tests pass verbose=False as 6th positional arg.
    if logger is None or isinstance(logger, bool):
        if isinstance(logger, bool):
            verbose = logger
        logger = VerboseStdoutLogger() if verbose else NullLogger()
    melee_weapons = [w for w in unit.weapons if w.melee]
    pistol_weapons = [w for w in unit.weapons if "PISTOL" in w.abilities and not w.melee]
    # Pistols can fire in melee — we already fired them in shooting phase if
    # engaged, so skip here (no double-fire).
    weapons = melee_weapons
    for weapon in weapons:
        # Pick a melee-engaged enemy
        engaged = [
            e for e in enemy_force.units
            if e.alive and id(e) in unit.engaged_with
        ]
        if not engaged:
            continue
        target = min(engaged, key=lambda e: e.total_wounds)
        dist = 0.0
        pre_models = target.models
        pre_ac = (
            target.attached_character.total_wounds
            if target.attached_character and target.attached_character.alive
            else 0
        )
        shot = resolve_shots(unit, weapon, target, dist, unit_force, rng)
        deaths = apply_damage_with_attachment(target, shot, None, unit_force, enemy_force)
        for d in deaths:
            apply_deadly_demise(d, unit_force, rng)
        logger.record({
            "round": round_no,
            "turn": turn_side,
            "phase": "fight",
            "type": "activation",
            "actor": unit.name,
            "target": target.name,
            "weapon": weapon.name + " (melee)",
            "attacks": shot.total_attacks,
            "hits": shot.hit_count,
            "wounds": shot.wound_count,
            "unsaved": shot.unsaved_count,
            "damage": shot.body_damage + shot.char_damage,
            "models_killed": max(0, pre_models - target.models),
            "attached_character_damage": max(
                0,
                pre_ac - (
                    target.attached_character.total_wounds
                    if target.attached_character and target.attached_character.alive
                    else 0
                ),
            ),
        })
        for d in deaths:
            logger.record({
                "round": round_no,
                "turn": turn_side,
                "phase": "fight",
                "type": "unit_destroyed",
                "actor": d.name,
            })
