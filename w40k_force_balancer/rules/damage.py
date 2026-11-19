"""Damage application primitives.

Splits bodyguard vs attached-character damage, handles squad model-pool
allocation, and applies self-inflicted mortals (Hazardous backlash).

Separated from `weapon_abilities` to let `unit_abilities.apply_deadly_demise`
re-use squad allocation without pulling in the full shot resolver.
"""
from __future__ import annotations

from ..core.model import Force, Unit


def apply_damage_to_squad(target: Unit, damage: int) -> int:
    """Allocate `damage` wound points to the squad's non-character pool first.
    Returns leftover damage that should spill to attached character."""
    remaining = damage
    while remaining > 0 and target.alive:
        if remaining >= target._current_model_wounds:
            remaining -= target._current_model_wounds
            target.models -= 1
            target.models_lost_this_round += 1
            target._current_model_wounds = (
                target.wounds_per_model if target.alive else 0
            )
        else:
            target._current_model_wounds -= remaining
            remaining = 0
    return remaining   # leftover, spills to character if attached


def apply_damage_with_attachment(
    squad: Unit,
    body_damage: int,
    character_damage: int,
    attacker_force: Force,
    defender_force: Force,
) -> list[Unit]:
    """Apply shoot/fight damage respecting Look Out Sir + Precision.

    Damage pipeline:
      1. Character-tagged damage (from Precision) goes directly to attached
         character; overflow back to body.
      2. Body damage goes to bodyguards first. When bodyguards wipe,
         remaining damage spills to character.

    Returns a list of units that died this activation (for Deadly Demise).
    """
    deaths: list[Unit] = []
    character = squad.attached_character

    # Precision path: hit the character directly.
    if character is not None and character.alive and character_damage > 0:
        leftover = apply_damage_to_squad(character, character_damage)
        if not character.alive:
            deaths.append(character)
            squad.attached_character = None
            character.attached_to = None
        body_damage += leftover

    # Body damage: squad takes it; if squad wipes with character still alive,
    # spill to character.
    if body_damage > 0:
        leftover = apply_damage_to_squad(squad, body_damage)
        if not squad.alive and character is not None and character.alive:
            # Character becomes a lone unit now; spill damage to it.
            squad.attached_character = None
            character.attached_to = None
            apply_damage_to_squad(character, leftover)
            if not character.alive:
                deaths.append(character)

    if not squad.alive and squad.attached_character is None:
        deaths.append(squad)

    return deaths


def apply_self_mortals(unit: Unit, mortals: int) -> None:
    """Hazardous backlash: unit takes `mortals` MW."""
    if mortals <= 0:
        return
    # MW bypasses saves; no FNP for Hazardous (11e: Hazardous mortals bypass
    # everything that doesn't specifically protect vs mortal wounds).
    apply_damage_to_squad(unit, mortals)
