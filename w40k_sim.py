#!/usr/bin/env python3
"""Warhammer 40k combat simulator — strips the game down to stat-driven
dice rolls so army compositions can be compared without trusting the
point system.

Scope (v1):
  * Two YAML force files in; win-odds out.
  * Standard 4-step combat: hit -> wound -> save -> FNP.
  * Movement, range, cover, and special rules are IGNORED.
  * Reports results for A-goes-first vs B-goes-first as separate columns
    plus the 50/50 blend.

Usage:
    python3 w40k_sim.py force_a.yaml force_b.yaml [--sims 10000] [--rounds 5]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

import yaml


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class Weapon:
    name: str
    attacks: int           # A characteristic. Supports simple ints only in v1.
    skill: int             # BS for ranged, WS for melee. 2+ to 6+.
    strength: int          # S
    ap: int                # Armor Pen, stored as positive (AP1 -> 1)
    damage: int            # D per unsaved wound. Ints only in v1.
    melee: bool = False    # Only affects accounting; otherwise identical.


@dataclass
class Unit:
    name: str
    models: int            # Starting model count. Decreases as models die.
    toughness: int         # T
    wounds_per_model: int  # W
    save: int              # Sv (armor). 2+ to 6+.
    inv_save: int | None = None   # Invulnerable save, better of inv vs modified Sv.
    fnp: int | None = None        # Feel no Pain, rolled per unsaved wound.
    weapons: list[Weapon] = field(default_factory=list)
    _current_model_wounds: int = 0  # Wounds remaining on the lead model.

    def copy(self) -> "Unit":
        return replace(
            self,
            weapons=list(self.weapons),
            _current_model_wounds=self.wounds_per_model,
        )

    @property
    def alive(self) -> bool:
        return self.models > 0

    @property
    def total_wounds(self) -> int:
        """Total wound points the unit can still absorb."""
        if self.models <= 0:
            return 0
        return (self.models - 1) * self.wounds_per_model + self._current_model_wounds


@dataclass
class Force:
    name: str
    units: list[Unit] = field(default_factory=list)

    def copy(self) -> "Force":
        return Force(name=self.name, units=[u.copy() for u in self.units])

    @property
    def alive(self) -> bool:
        return any(u.alive for u in self.units)

    @property
    def total_wounds(self) -> int:
        return sum(u.total_wounds for u in self.units)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_force(path: Path) -> Force:
    """Load a Force from a YAML file.

    Expected structure (ints only; no dice strings in v1):
        name: "Space Marines"
        units:
          - name: "Intercessor squad"
            models: 5
            T: 4
            W: 2
            Sv: 3
            InvSv: null
            FNP: null
            weapons:
              - { name: Bolt rifle, A: 2, BS: 3, S: 4, AP: 1, D: 1 }
              - { name: Chainsword, A: 3, WS: 3, S: 4, AP: 0, D: 1, melee: true }
    """
    data = yaml.safe_load(path.read_text())
    units = []
    for u in data["units"]:
        weapons = []
        for w in u.get("weapons", []):
            weapons.append(
                Weapon(
                    name=w["name"],
                    attacks=int(w["A"]),
                    skill=int(w.get("BS", w.get("WS"))),
                    strength=int(w["S"]),
                    ap=int(w.get("AP", 0)),
                    damage=int(w["D"]),
                    melee=bool(w.get("melee", False)),
                )
            )
        unit = Unit(
            name=u["name"],
            models=int(u["models"]),
            toughness=int(u["T"]),
            wounds_per_model=int(u["W"]),
            save=int(u["Sv"]),
            inv_save=int(u["InvSv"]) if u.get("InvSv") else None,
            fnp=int(u["FNP"]) if u.get("FNP") else None,
            weapons=weapons,
        )
        unit._current_model_wounds = unit.wounds_per_model
        units.append(unit)
    return Force(name=data["name"], units=units)


# --------------------------------------------------------------------------- #
# Combat primitives
# --------------------------------------------------------------------------- #


def to_wound_threshold(strength: int, toughness: int) -> int:
    """Classic 40k to-wound chart."""
    if strength >= 2 * toughness:
        return 2
    if strength > toughness:
        return 3
    if strength == toughness:
        return 4
    if strength * 2 <= toughness:
        return 6
    return 5  # S < T but not <= T/2


def roll_d6(rng: random.Random) -> int:
    return rng.randint(1, 6)


def resolve_weapon_attack(
    weapon: Weapon,
    shots: int,
    target: Unit,
    rng: random.Random,
) -> int:
    """Returns total wounds (damage points) inflicted on target *before*
    allocation. Target handles death accounting externally.

    Standard pipeline:
      shots -> hits (d6 >= skill)
            -> wounds (d6 >= to-wound chart threshold)
            -> failed-saves (d6 < modified save AND d6 < inv save)
            -> damage (D per failed save)
            -> FNP (per *wound point*, d6 >= FNP ignores it)
    """
    if shots <= 0 or not target.alive:
        return 0

    # Hit
    hits = sum(1 for _ in range(shots) if roll_d6(rng) >= weapon.skill)
    if not hits:
        return 0

    # Wound
    wound_th = to_wound_threshold(weapon.strength, target.toughness)
    wounds = sum(1 for _ in range(hits) if roll_d6(rng) >= wound_th)
    if not wounds:
        return 0

    # Save: take the BETTER of modified armor and invulnerable
    modified_save = target.save + weapon.ap  # higher = worse
    unsaved = 0
    for _ in range(wounds):
        armor_roll = roll_d6(rng)
        armor_ok = modified_save <= 6 and armor_roll >= modified_save
        inv_ok = False
        if target.inv_save is not None:
            inv_roll = roll_d6(rng)
            inv_ok = inv_roll >= target.inv_save
        if not (armor_ok or inv_ok):
            unsaved += 1
    if not unsaved:
        return 0

    # Damage + FNP
    raw_damage = unsaved * weapon.damage
    if target.fnp is None:
        return raw_damage
    # FNP: roll per wound point. Ignore on >= fnp.
    ignored = sum(1 for _ in range(raw_damage) if roll_d6(rng) >= target.fnp)
    return max(0, raw_damage - ignored)


def apply_damage(target: Unit, damage: int) -> None:
    """Allocate incoming wound points to the unit, killing lead models."""
    remaining = damage
    while remaining > 0 and target.alive:
        if remaining >= target._current_model_wounds:
            remaining -= target._current_model_wounds
            target.models -= 1
            target._current_model_wounds = (
                target.wounds_per_model if target.alive else 0
            )
        else:
            target._current_model_wounds -= remaining
            remaining = 0


def pick_target(enemy_force: Force, rng: random.Random) -> Unit | None:
    """Target selection: closest-to-dying first. Breaks fire-for-effect
    decisions deterministically so sim variance stays in dice, not choices.
    Falls back to random if multiple ties."""
    alive = [u for u in enemy_force.units if u.alive]
    if not alive:
        return None
    min_wounds = min(u.total_wounds for u in alive)
    candidates = [u for u in alive if u.total_wounds == min_wounds]
    return rng.choice(candidates)


def fire_force(
    attacker: Force,
    defender: Force,
    rng: random.Random,
) -> None:
    """One force fires every weapon of every surviving unit at the enemy.
    Each attacking unit picks its own target; concentration emerges from
    the target-selection heuristic above."""
    for unit in attacker.units:
        if not unit.alive:
            continue
        target = pick_target(defender, rng)
        if target is None:
            return  # enemy wiped mid-turn
        for weapon in unit.weapons:
            # A characteristic multiplies by surviving model count.
            total_shots = weapon.attacks * unit.models
            damage = resolve_weapon_attack(weapon, total_shots, target, rng)
            if damage:
                apply_damage(target, damage)
                if not target.alive:
                    target = pick_target(defender, rng)
                    if target is None:
                        return


# --------------------------------------------------------------------------- #
# Game loop
# --------------------------------------------------------------------------- #


def simulate_game(
    force_a: Force,
    force_b: Force,
    rounds: int,
    a_goes_first: bool,
    rng: random.Random,
) -> str:
    """Returns 'A', 'B', or 'draw'. Each round, both sides fire once in
    the chosen order."""
    a = force_a.copy()
    b = force_b.copy()
    first, second = (a, b) if a_goes_first else (b, a)

    for _ in range(rounds):
        if not first.alive or not second.alive:
            break
        fire_force(first, second, rng)
        if not second.alive:
            break
        fire_force(second, first, rng)
        if not first.alive:
            break

    if a.alive and not b.alive:
        return "A"
    if b.alive and not a.alive:
        return "B"
    # Both alive after N rounds — compare remaining wound totals.
    if a.total_wounds > b.total_wounds:
        return "A"
    if b.total_wounds > a.total_wounds:
        return "B"
    return "draw"


def simulate_many(
    force_a: Force,
    force_b: Force,
    sims: int,
    rounds: int,
    a_goes_first: bool,
    seed: int,
) -> dict[str, float]:
    rng = random.Random(seed)
    counts: dict[str, int] = defaultdict(int)
    for _ in range(sims):
        counts[simulate_game(force_a, force_b, rounds, a_goes_first, rng)] += 1
    total = sum(counts.values()) or 1
    return {k: counts[k] / total for k in ("A", "B", "draw")}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def pct(f: float) -> str:
    return f"{f * 100:5.1f}%"


def print_report(
    force_a: Force,
    force_b: Force,
    sims: int,
    rounds: int,
    seed: int,
) -> None:
    res_a_first = simulate_many(force_a, force_b, sims, rounds, True, seed)
    res_b_first = simulate_many(force_a, force_b, sims, rounds, False, seed + 1)
    blend = {
        k: (res_a_first[k] + res_b_first[k]) / 2
        for k in ("A", "B", "draw")
    }

    def wounds_summary(f: Force) -> str:
        total = f.total_wounds
        models = sum(u.models for u in f.units)
        units = len(f.units)
        return f"{units} units / {models} models / {total} wound points"

    print(
        f"\n{force_a.name}  vs  {force_b.name}"
        f"\n  A: {wounds_summary(force_a)}"
        f"\n  B: {wounds_summary(force_b)}"
        f"\n  {sims:,} sims x {rounds} rounds each\n"
    )
    print(f"  {'':24}  A wins   B wins    draw")
    print(f"  {'A goes first':24}  "
          f"{pct(res_a_first['A'])}  {pct(res_a_first['B'])}  {pct(res_a_first['draw'])}")
    print(f"  {'B goes first':24}  "
          f"{pct(res_b_first['A'])}  {pct(res_b_first['B'])}  {pct(res_b_first['draw'])}")
    print(f"  {'50/50 blend':24}  "
          f"{pct(blend['A'])}  {pct(blend['B'])}  {pct(blend['draw'])}")

    swing = (res_a_first['A'] - res_b_first['A']) * 100
    if abs(swing) >= 1.0:
        print(f"\n  First-turn advantage: {swing:+.1f}pp for A when A goes first")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("force_a", type=Path)
    parser.add_argument("force_b", type=Path)
    parser.add_argument("--sims", type=int, default=10_000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    force_a = load_force(args.force_a)
    force_b = load_force(args.force_b)
    print_report(force_a, force_b, args.sims, args.rounds, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
