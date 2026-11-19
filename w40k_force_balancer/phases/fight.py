"""Fight phase — Fights-First / Normal / Fights-Last tiers, alternating activations."""
from __future__ import annotations

import random

from ..core.model import Force, Unit
from ..rules.damage import apply_damage_with_attachment
from ..rules.unit_abilities import apply_deadly_demise
from ..rules.weapon_abilities import resolve_shots


def fight_phase(
    first_force: Force,
    second_force: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    """Resolve the Fight phase. Fights First tier, then Normal, then Fights
    Last. Within each tier, alternate activations starting with the player
    whose turn it is."""
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
                    _fight_activation(u, first_force, second_force, round_no, rng, verbose)
            if queue_second:
                u = queue_second.pop(0)
                if u.alive and u.engaged_with:
                    _fight_activation(u, second_force, first_force, round_no, rng, verbose)


def _fight_activation(
    unit: Unit,
    unit_force: Force,
    enemy_force: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool,
) -> None:
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
        body, char, _ = resolve_shots(unit, weapon, target, dist, unit_force, rng)
        deaths = apply_damage_with_attachment(target, body, char, unit_force, enemy_force)
        for d in deaths:
            apply_deadly_demise(d, unit_force, rng)
        if verbose and (body or char):
            print(f"    [{unit_force.name}] FIGHT {unit.name} {weapon.name} -> {target.name} dmg={body}+{char}")
