#!/usr/bin/env python3
"""Warhammer 40k combat simulator v2.

Scope (v2):
  * Spatial 1D-collapse model (unit-to-unit scalar distance).
  * Full phase loop: Command -> Movement -> Shooting -> Charge -> Fight -> Morale.
  * Weapon special rules: Sustained Hits, Lethal Hits, Devastating Wounds,
    Twin-linked, Torrent, Melta, Rapid Fire, Blast, Hazardous, Anti-X,
    Pistol, Heavy, Precision.
  * Unit abilities: Feel No Pain, Deep Strike, Stealth, Fights First,
    Deadly Demise, Infiltrators, Scouts, For the Greater Good, Markerlight.
  * Character attachment with Look Out Sir + Precision.
  * CP economy + stratagem usage (simple decision rules).
  * Detachment abilities: Shield Host (Martial Ka'tah), Mont'ka.
  * Battleshock (morale).

Output shape mirrors v1 — A-first / B-first / 50/50 blend.

Usage:
    python3 w40k_sim_v2.py force_a.yaml force_b.yaml \\
        [--sims 10000] [--rounds 5] [--seed 0] \\
        [--board-width 44] [--board-height 30] [--deployment-gap 24] \\
        [--verbose]

Catalog paths are resolved relative to this script, or overridden with
--catalog-dir. Unknown ability / keyword / detachment / stratagem names
raise RuntimeError at load time.

STAT-APPROX flags on every expected-value shortcut; grep the file to audit.

Statistical approximations active in this sim (fidelity shortcuts):
  1. 1D distance collapse — each unit has a scalar `pos` = inches advanced
     from its own deployment edge. Left-right drift is ignored. Impact: no
     true LoS, no flanking, no pile-in geometry.
  2. Precision character allocation — when a Precision weapon targets a
     bodyguard squad with an attached character, exactly 50% of landed
     damage lands on the character directly (ceil(n/2)). Actual 40k lets
     the attacker allocate per-hit.
  3. Markerlight re-roll effect — 2+ markers on a target buff the
     effective BS of subsequent T'au ranged shots by +1 (lowered skill
     target), approximating "re-roll all failed to-hit."
  4. Grenade stratagem — now samples 1d6 properly (expected value 3.5); the
     earlier version used 6 attacks, which is MAX not expected and biased
     damage upward. Sampling keeps the variance in the right bucket.
  5. Overwatch applies the strat universally (defender's BS is patched
     to 6+ / 5+ for the activation) rather than being a reaction.
  6. Independent-rolls save model — armor save and invulnerable save are
     rolled independently; outcome is equivalent to "take the better" under
     independent-rolls assumption.
  7. Devastating Wound damage does not get further FNP ignore rolls.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Optional

import yaml


# =========================================================================== #
# Catalog
# =========================================================================== #


CATALOG_DIR_DEFAULT = Path(__file__).parent / "catalog"


@dataclass
class CatalogEntry:
    id: str
    category: str              # weapon | unit | stratagem | detachment
    effect: str                # dispatch key used by the sim
    params: dict               # default parameters
    notes: str = ""


@dataclass
class Detachment:
    name: str
    faction: str
    army_ability: str          # id into Catalog.abilities
    stratagems: list[str]      # ids into Catalog.abilities (category=stratagem)


@dataclass
class Catalog:
    abilities: dict[str, CatalogEntry] = field(default_factory=dict)
    keywords: set[str] = field(default_factory=set)
    factions: set[str] = field(default_factory=set)
    sub_keywords: set[str] = field(default_factory=set)
    detachments: dict[str, Detachment] = field(default_factory=dict)

    def require_ability(self, ability_id: str, expected_category: str | None = None) -> CatalogEntry:
        if ability_id not in self.abilities:
            raise RuntimeError(
                f"Unknown ability '{ability_id}'. Add it to catalog/abilities.yaml "
                f"before referencing it in force yamls."
            )
        entry = self.abilities[ability_id]
        if expected_category and entry.category != expected_category:
            raise RuntimeError(
                f"Ability '{ability_id}' is category '{entry.category}' but "
                f"expected '{expected_category}'."
            )
        return entry

    def require_keyword(self, kw: str) -> None:
        # Universal / faction / sub — any one of these is OK.
        if kw in self.keywords:
            return
        if kw in self.factions:
            return
        if kw in self.sub_keywords:
            return
        # Free-form sub-keywords are allowed (sim only reasons about universals).
        # BUT if it looks like a universal (all caps, no underscores to indicate
        # a sub-keyword naming convention) we still fail loud.
        if kw.isupper() and "_" not in kw and len(kw) < 20:
            # Looks universal-ish. Require it in the catalog.
            raise RuntimeError(
                f"Unknown keyword '{kw}'. Add it to catalog/keywords.yaml "
                f"(universal / factions / sub) or namespace it with an underscore."
            )
        # Otherwise treat as free-form datasheet label (silently accepted).


def load_catalog(catalog_dir: Path | None = None) -> Catalog:
    """Load the ability + keyword + detachment catalog from disk."""
    cdir = catalog_dir or CATALOG_DIR_DEFAULT
    if not cdir.exists():
        raise RuntimeError(f"Catalog directory does not exist: {cdir}")

    cat = Catalog()

    # Abilities
    ab_path = cdir / "abilities.yaml"
    if not ab_path.exists():
        raise RuntimeError(f"Missing abilities catalog: {ab_path}")
    ab_data = yaml.safe_load(ab_path.read_text()) or {}
    for aid, spec in ab_data.items():
        cat.abilities[aid] = CatalogEntry(
            id=aid,
            category=spec["category"],
            effect=spec["effect"],
            params=dict(spec.get("params") or {}),
            notes=spec.get("notes", ""),
        )

    # Keywords
    kw_path = cdir / "keywords.yaml"
    if not kw_path.exists():
        raise RuntimeError(f"Missing keywords catalog: {kw_path}")
    kw_data = yaml.safe_load(kw_path.read_text()) or {}
    cat.keywords = set(kw_data.get("universal") or [])
    cat.factions = set(kw_data.get("factions") or [])
    cat.sub_keywords = set(kw_data.get("sub") or [])

    # Detachments
    det_dir = cdir / "detachments"
    if det_dir.exists():
        for det_path in sorted(det_dir.glob("*.yaml")):
            dd = yaml.safe_load(det_path.read_text()) or {}
            name = dd["name"]
            det = Detachment(
                name=name,
                faction=dd["faction"],
                army_ability=dd["army_ability"],
                stratagems=list(dd.get("stratagems") or []),
            )
            # Validate ability refs exist in abilities.yaml
            cat.require_ability(det.army_ability, expected_category="detachment")
            for sid in det.stratagems:
                cat.require_ability(sid, expected_category="stratagem")
            if det.faction not in cat.factions:
                raise RuntimeError(
                    f"Detachment '{name}' faction '{det.faction}' not in catalog/keywords.yaml factions"
                )
            # Keyed by filename (without .yaml) AND by name for convenience
            key = det_path.stem
            cat.detachments[key] = det
    return cat


# =========================================================================== #
# Data model
# =========================================================================== #


# Phase constants
PHASE_COMMAND = "COMMAND"
PHASE_MOVEMENT = "MOVEMENT"
PHASE_SHOOTING = "SHOOTING"
PHASE_CHARGE = "CHARGE"
PHASE_FIGHT = "FIGHT"
PHASE_MORALE = "MORALE"
ALL_PHASES = [PHASE_COMMAND, PHASE_MOVEMENT, PHASE_SHOOTING, PHASE_CHARGE, PHASE_FIGHT, PHASE_MORALE]


@dataclass
class Weapon:
    name: str
    attacks: int
    skill: int                 # BS for ranged, WS for melee
    strength: int
    ap: int                    # positive = AP1, AP2, etc.
    damage: int
    melee: bool = False
    range_in: int = 0          # 0 for melee (or unused)
    abilities: dict[str, dict] = field(default_factory=dict)
    # Each ability stores its resolved params (catalog defaults + overrides).


@dataclass
class Unit:
    name: str
    models: int                # starting / current count
    toughness: int
    wounds_per_model: int
    save: int
    inv_save: int | None = None
    fnp: int | None = None
    movement: int = 6          # M in inches
    leadership: int = 7        # Ld; test is 2d6 + lost >= Ld to pass
    oc: int = 1                # Objective Control
    keywords: list[str] = field(default_factory=list)
    abilities: dict[str, dict] = field(default_factory=dict)
    weapons: list[Weapon] = field(default_factory=list)
    leader_name: str | None = None   # If set: this unit is a character; attached to squad with this name.
    starting_models: int = 0         # captured at load

    # Runtime state
    _current_model_wounds: int = 0
    pos: float = 0.0           # inches advanced from own deployment line
    in_reserves: bool = False
    arrived_round: int = 0
    engaged_with: set[int] = field(default_factory=set)   # stores id(unit) of melee partners
    moved_this_turn: bool = False
    advanced_this_turn: bool = False
    remained_stationary: bool = True
    battleshocked_until_round: int = 0
    models_lost_this_round: int = 0

    # Attachment linkage. If this unit has a leader attached from another unit,
    # we add the leader's wound pool as `attached_character_wounds`.
    attached_character: "Unit | None" = None   # Reference from squad -> character
    attached_to: "Unit | None" = None          # Reference from character -> squad

    def copy(self) -> "Unit":
        clone = replace(
            self,
            weapons=[replace(w, abilities=dict(w.abilities)) for w in self.weapons],
            abilities={k: dict(v) for k, v in self.abilities.items()},
            keywords=list(self.keywords),
            engaged_with=set(),
        )
        clone._current_model_wounds = self.wounds_per_model
        clone.starting_models = self.starting_models or self.models
        clone.attached_character = None
        clone.attached_to = None
        return clone

    @property
    def alive(self) -> bool:
        return self.models > 0

    @property
    def total_wounds(self) -> int:
        if self.models <= 0:
            return 0
        return (self.models - 1) * self.wounds_per_model + self._current_model_wounds

    def has_ability(self, aid: str) -> bool:
        return aid in self.abilities

    def has_keyword(self, kw: str) -> bool:
        return kw in self.keywords


@dataclass
class Force:
    name: str
    faction: str | None = None
    detachment: Detachment | None = None
    cp: int = 4
    units: list[Unit] = field(default_factory=list)

    # Runtime state
    martial_katah_target: Unit | None = None          # Custodes: this round's wound-bonus target
    montka_target: Unit | None = None                 # T'au: this round's double-shoot unit
    markerlights: dict[int, int] = field(default_factory=dict)   # id(enemy_unit) -> marker count
    used_strats_this_round: set[tuple[str, int]] = field(default_factory=set)   # (strat_id, round)
    used_strats_this_phase: set[str] = field(default_factory=set)
    rapid_ingress_used: bool = False
    insane_bravery_used_this_round: bool = False

    def copy(self) -> "Force":
        f = Force(
            name=self.name,
            faction=self.faction,
            detachment=self.detachment,
            cp=self.cp,
            units=[u.copy() for u in self.units],
        )
        # Restore attachments by name
        by_name = {u.name: u for u in f.units}
        for original, cloned in zip(self.units, f.units):
            if original.leader_name:
                cloned.leader_name = original.leader_name
                squad = by_name.get(original.leader_name)
                if squad is not None:
                    cloned.attached_to = squad
                    squad.attached_character = cloned
        return f

    @property
    def alive(self) -> bool:
        return any(u.alive for u in self.units if not u.in_reserves)

    @property
    def total_wounds(self) -> int:
        return sum(u.total_wounds for u in self.units if not u.in_reserves)

    def living_on_board(self) -> list[Unit]:
        return [u for u in self.units if u.alive and not u.in_reserves]


@dataclass
class Board:
    width_in: int = 44
    height_in: int = 30
    deployment_gap_in: int = 24       # inches between the two deployment edges


# =========================================================================== #
# Loading
# =========================================================================== #


def _parse_weapon(w: dict, cat: Catalog) -> Weapon:
    ab = {}
    for raw in w.get("abilities", []) or []:
        if isinstance(raw, str):
            aid = raw
            overrides = {}
        elif isinstance(raw, dict):
            aid = raw.get("id") or raw.get("name")
            if aid is None:
                raise RuntimeError(f"Weapon ability without id: {raw}")
            overrides = {k: v for k, v in raw.items() if k not in ("id", "name")}
        else:
            raise RuntimeError(f"Weapon ability malformed: {raw!r}")
        entry = cat.require_ability(aid, expected_category="weapon")
        params = dict(entry.params)
        params.update(overrides)
        ab[aid] = params
    return Weapon(
        name=w["name"],
        attacks=int(w["A"]),
        skill=int(w.get("BS", w.get("WS", 4))),
        strength=int(w["S"]),
        ap=int(w.get("AP", 0)),
        damage=int(w["D"]),
        melee=bool(w.get("melee", False)),
        range_in=int(w.get("range", 0 if w.get("melee") else 24)),
        abilities=ab,
    )


def _parse_unit(u: dict, cat: Catalog) -> Unit:
    # Validate keywords
    for kw in u.get("keywords", []) or []:
        cat.require_keyword(kw)
    # Build ability dict
    abilities: dict[str, dict] = {}
    for raw in u.get("abilities", []) or []:
        if isinstance(raw, str):
            aid = raw
            overrides = {}
        elif isinstance(raw, dict):
            aid = raw.get("id") or raw.get("name")
            if aid is None:
                raise RuntimeError(f"Unit ability without id: {raw}")
            overrides = {k: v for k, v in raw.items() if k not in ("id", "name")}
        else:
            raise RuntimeError(f"Unit ability malformed: {raw!r}")
        entry = cat.require_ability(aid)
        if entry.category not in ("unit", "detachment"):
            raise RuntimeError(
                f"Unit ability '{aid}' has category '{entry.category}' — "
                f"only unit/detachment categories are allowed on a unit."
            )
        params = dict(entry.params)
        params.update(overrides)
        abilities[aid] = params
    weapons = [_parse_weapon(w, cat) for w in u.get("weapons", []) or []]

    # Required-fields loud failures
    required = ["name", "models", "T", "W", "Sv"]
    for r in required:
        if r not in u:
            raise RuntimeError(
                f"Unit '{u.get('name', '???')}' missing required field '{r}' "
                f"(need: {required})"
            )
    unit = Unit(
        name=u["name"],
        models=int(u["models"]),
        toughness=int(u["T"]),
        wounds_per_model=int(u["W"]),
        save=int(u["Sv"]),
        inv_save=int(u["InvSv"]) if u.get("InvSv") else None,
        fnp=int(u["FNP"]) if u.get("FNP") else None,
        movement=int(u.get("M", 6)),
        leadership=int(u.get("Ld", 7)),
        oc=int(u.get("OC", 1)),
        keywords=list(u.get("keywords", []) or []),
        abilities=abilities,
        weapons=weapons,
        leader_name=u.get("leader"),
    )
    unit.starting_models = unit.models
    unit._current_model_wounds = unit.wounds_per_model
    return unit


def load_force(path: Path, catalog: Catalog) -> Force:
    """Load a Force from a YAML file. Validates every ability/keyword/detachment
    against the catalog; unknown names raise RuntimeError."""
    data = yaml.safe_load(path.read_text())
    if "name" not in data:
        raise RuntimeError(f"Force yaml {path} missing required 'name'")
    if "units" not in data:
        raise RuntimeError(f"Force yaml {path} missing required 'units'")
    faction = data.get("faction")
    if faction is not None and faction not in catalog.factions:
        raise RuntimeError(
            f"Force '{data['name']}' faction '{faction}' not in catalog "
            f"(see catalog/keywords.yaml factions)."
        )
    det_key = data.get("detachment")
    detachment = None
    if det_key is not None:
        if det_key not in catalog.detachments:
            raise RuntimeError(
                f"Force '{data['name']}' detachment '{det_key}' not found. "
                f"Available: {sorted(catalog.detachments)}"
            )
        detachment = catalog.detachments[det_key]
        if faction and detachment.faction != faction:
            raise RuntimeError(
                f"Detachment '{detachment.name}' is faction '{detachment.faction}' "
                f"but force '{data['name']}' is '{faction}'."
            )
    units = [_parse_unit(u, catalog) for u in data["units"]]

    # Wire character attachments
    by_name = {u.name: u for u in units}
    for u in units:
        if u.leader_name:
            if u.leader_name not in by_name:
                raise RuntimeError(
                    f"Unit '{u.name}' has leader: '{u.leader_name}' but no unit of "
                    f"that name exists in this force."
                )
            squad = by_name[u.leader_name]
            if squad.attached_character is not None:
                raise RuntimeError(
                    f"Squad '{squad.name}' already has an attached character "
                    f"'{squad.attached_character.name}'; can't also attach '{u.name}'."
                )
            squad.attached_character = u
            u.attached_to = squad

    force = Force(
        name=data["name"],
        faction=faction,
        detachment=detachment,
        cp=int(data.get("cp", 4)),
        units=units,
    )
    # Deep-strike reserves setup
    for u in force.units:
        if u.has_ability("DEEP_STRIKE"):
            u.in_reserves = True
    return force


# =========================================================================== #
# Combat primitives
# =========================================================================== #


def to_wound_threshold(strength: int, toughness: int) -> int:
    if strength >= 2 * toughness:
        return 2
    if strength > toughness:
        return 3
    if strength == toughness:
        return 4
    if strength * 2 <= toughness:
        return 6
    return 5


def roll_d6(rng: random.Random) -> int:
    return rng.randint(1, 6)


def roll_2d6(rng: random.Random) -> int:
    return rng.randint(1, 6) + rng.randint(1, 6)


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def best_fnp(unit: Unit) -> int | None:
    """Return effective FNP threshold (lower is better), merging native FNP
    field with any FEEL_NO_PAIN ability."""
    native = unit.fnp
    ab = unit.abilities.get("FEEL_NO_PAIN")
    ab_fnp = int(ab.get("n", 5)) if ab else None
    candidates = [v for v in (native, ab_fnp) if v is not None]
    return min(candidates) if candidates else None


# =========================================================================== #
# Shoot resolution with special rules
# =========================================================================== #


def resolve_shots(
    attacker: Unit,
    weapon: Weapon,
    target: Unit,
    distance: float,
    attacker_force: "Force",
    rng: random.Random,
    allow_crit_hit_bonus: bool = True,
) -> tuple[int, int, int]:
    """Resolve one activation of a weapon by `attacker` against `target`.

    Returns (damage_points_to_bodyguard, damage_points_to_character, self_mortals).
    `self_mortals` is Hazardous backlash from 1s on hit rolls.

    All weapon abilities + unit abilities are applied here.
    """
    if not weapon.melee:
        # Range gate: can only shoot if within weapon range.
        if distance > weapon.range_in:
            return (0, 0, 0)

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
        return (0, 0, 0)

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

    if torrent:
        hits = total_shots
        crit_hits = 0
    else:
        for _ in range(total_shots):
            raw = roll_d6(rng)
            if raw == 1 and hazardous:
                hazardous_mortals += 1
            # Unmodified 1 always misses; unmodified 6 always hits (crit).
            if raw == 1:
                continue
            if raw == 6:
                crit_hits += 1
                hits += 1
            elif raw >= effective_hit:
                hits += 1

    # Sustained Hits: crit hits add n additional auto-hits
    if sustained and allow_crit_hit_bonus:
        hits += crit_hits * int(sustained.get("n", 1))

    # Lethal Hits: crit hits become auto-wounds, removed from the hit pool
    if lethal_hits and not torrent:
        lethal_autowounds = crit_hits
        hits -= crit_hits   # those hits bypass to-wound

    if hits <= 0 and lethal_autowounds <= 0:
        return (0, 0, hazardous_mortals)

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
        return (0, 0, hazardous_mortals)

    # --- Devastating Wounds split (bypass save + FNP) ---------------------
    devastating_wounds = crit_wounds if devastating else 0
    normal_wounds = wounds - devastating_wounds

    # --- Save step for the normal wounds ---------------------------------
    unsaved = 0
    modified_save = target.save + weapon.ap
    inv = target.inv_save
    for _ in range(normal_wounds):
        armor_ok = modified_save <= 6 and roll_d6(rng) >= modified_save
        inv_ok = False
        if inv is not None:
            inv_ok = roll_d6(rng) >= inv
        # Take the better of armor and invuln — if either passes, saved.
        # Note: in actual 40k you pick one; same probabilistic outcome under
        # independent-rolls approximation we're using.
        if not (armor_ok or inv_ok):
            unsaved += 1

    # --- Damage calc for normal unsaved wounds ---------------------------
    damage_per = weapon.damage
    melta = weapon.abilities.get("MELTA")
    if melta and not weapon.melee:
        half = weapon.range_in / 2.0
        if distance <= half:
            damage_per += int(melta.get("n", 2))
    # Devastating wounds: `damage` mortals per crit, bypassing saves+FNP.
    mortal_damage_points = devastating_wounds * weapon.damage

    raw_damage = unsaved * damage_per

    # --- FNP (applied per wound point, not per unsaved-hit) --------------
    fnp = best_fnp(target)
    if fnp is not None and raw_damage > 0:
        ignored = sum(1 for _ in range(raw_damage) if roll_d6(rng) >= fnp)
        raw_damage = max(0, raw_damage - ignored)
    # Mortals from devastating wounds ignore FNP. (11th ed Dev Wounds are
    # mortal wounds now; some editions let FNP apply. We follow 11th:
    # mortals bypass FNP unless native unit has a specific anti-mortal FNP.
    # For sim simplicity, FNP does NOT apply to Devastating Wound mortals.)

    total_damage = raw_damage + mortal_damage_points

    # --- Precision: Character allocation ---------------------------------
    damage_character = 0
    damage_body = total_damage
    if "PRECISION" in weapon.abilities and target.attached_character is not None:
        # STAT-APPROX: 50% of total damage lands on the character directly,
        # bypassing Look Out Sir. Round half-up.
        damage_character = (total_damage + 1) // 2
        damage_body = total_damage - damage_character

    return (damage_body, damage_character, hazardous_mortals)


# =========================================================================== #
# Damage application
# =========================================================================== #


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


def apply_deadly_demise(
    dying: Unit,
    opposing_force: Force,
    rng: random.Random,
) -> None:
    """On destruction, roll per DEADLY_DEMISE. Dealt to closest enemy unit."""
    dd = dying.abilities.get("DEADLY_DEMISE")
    if not dd:
        return
    threshold = int(dd.get("threshold", 4))
    n = int(dd.get("n", 1))
    if roll_d6(rng) < threshold:
        return
    # Closest enemy by pair-distance
    candidates = [u for u in opposing_force.living_on_board()]
    if not candidates:
        return
    # dying.pos is already set when it died; pair distance:
    def pd(u: Unit) -> float:
        return pair_distance(dying, u)
    target = min(candidates, key=pd)
    apply_damage_to_squad(target, n)


# =========================================================================== #
# Spatial helpers
# =========================================================================== #


def pair_distance(a: Unit, b: Unit) -> float:
    """Distance in inches between unit a (one force) and unit b (opposing).

    Each unit's `pos` is advance from its own deployment line (0.0 at deploy,
    growing positive as it moves toward enemy). Battleground.deployment_gap
    is the total inches between the two deployment lines at setup.

    A and B are moving toward each other, so remaining gap = gap - a.pos - b.pos.
    Clamped at 0 (engaged).
    """
    # Both share reference to a Board, but we need the board distance. We
    # stash the gap in a module-level var for simplicity in this function,
    # updated by the game loop.
    return max(0.0, _BOARD.deployment_gap_in - a.pos - b.pos)


# Module-level board handle, set by simulate_game before combat starts.
_BOARD = Board()


def closest_enemy(unit: Unit, enemy_force: Force) -> Unit | None:
    live = [u for u in enemy_force.living_on_board()]
    if not live:
        return None
    return min(live, key=lambda e: pair_distance(unit, e))


def closest_enemy_within(unit: Unit, enemy_force: Force, max_dist: float) -> Unit | None:
    live = [u for u in enemy_force.living_on_board() if pair_distance(unit, u) <= max_dist]
    if not live:
        return None
    return min(live, key=lambda e: pair_distance(unit, e))


# =========================================================================== #
# Phases
# =========================================================================== #


def command_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    # +1 CP per round (from round 2 on in 11e, but we give from round 1 to keep it simple)
    if round_no >= 2:
        current.cp += 1
    current.used_strats_this_phase = set()
    current.insane_bravery_used_this_round = False

    # Battleshock tests (11e fires at start of command phase technically — the
    # morale phase at round-end is a sim convenience).

    # Detachment declarations
    current.martial_katah_target = None
    current.montka_target = None
    if current.detachment is None:
        return
    det_ab = current.detachment.army_ability
    if det_ab == "MARTIAL_KATAH":
        # Pick closest enemy as the katah target (simple heuristic — bias toward melee).
        closest = None
        best_dist = float("inf")
        for u in current.units:
            if not u.alive or u.in_reserves:
                continue
            e = closest_enemy(u, enemy)
            if e is None:
                continue
            d = pair_distance(u, e)
            if d < best_dist:
                best_dist = d
                closest = e
        current.martial_katah_target = closest
        if verbose and closest:
            print(f"    [{current.name}] Martial Ka'tah on {closest.name}")
    elif det_ab == "MONTKA":
        # Pick highest-damage-potential T'au unit as double-shoot target.
        candidates = [u for u in current.units if u.alive and not u.in_reserves]
        ranged = [u for u in candidates if any(not w.melee for w in u.weapons)]
        pool = ranged or candidates
        if pool:
            # Heuristic: pick by (A * models) of ranged weapons.
            def shoot_score(u: Unit) -> int:
                return sum(w.attacks * u.models for w in u.weapons if not w.melee)
            current.montka_target = max(pool, key=shoot_score)
            if verbose:
                print(f"    [{current.name}] Mont'ka target: {current.montka_target.name}")

    # Rapid Ingress (once per game, bring a deep-striker on round 1)
    if (
        round_no == 1
        and not current.rapid_ingress_used
        and current.detachment
        and "RAPID_INGRESS" in current.detachment.stratagems
        and current.cp >= 1
    ):
        for u in current.units:
            if u.in_reserves and u.has_ability("DEEP_STRIKE"):
                u.in_reserves = False
                u.arrived_round = 1
                u.pos = max(0.0, _BOARD.deployment_gap_in - 9)   # 9" from enemy edge
                current.cp -= 1
                current.rapid_ingress_used = True
                current.used_strats_this_round.add(("RAPID_INGRESS", round_no))
                if verbose:
                    print(f"    [{current.name}] Rapid Ingress: {u.name} drops in")
                break


def movement_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    # Deep-strike arrivals (default round 2)
    for u in current.units:
        if u.in_reserves:
            ds = u.abilities.get("DEEP_STRIKE", {})
            arrival = int(ds.get("arrival_round", 2))
            if round_no >= arrival:
                u.in_reserves = False
                u.arrived_round = round_no
                # Arrive 9" from enemy edge (= board.gap - 9 from own side).
                u.pos = max(0.0, _BOARD.deployment_gap_in - int(ds.get("range_in", 9)))
                # 11e: arriving from reserves counts as having moved — skip
                # normal movement this turn.
                u.moved_this_turn = True
                u.remained_stationary = False
                if verbose:
                    print(f"    [{current.name}] {u.name} deep-strikes in at pos={u.pos:.1f}")

    # Pre-game-ish: Infiltrators + Scouts already baked into initial pos by
    # setup_initial_positions; nothing to do here.

    for u in current.units:
        if not u.alive or u.in_reserves:
            continue
        # Units that just arrived from reserves this phase already moved.
        if u.arrived_round == round_no:
            continue
        u.moved_this_turn = False
        u.advanced_this_turn = False
        u.remained_stationary = True

        # Engaged units can only Fall Back; we don't model fallback choice. Skip.
        if u.engaged_with:
            continue

        # Target: closest enemy.
        enemy_target = closest_enemy(u, enemy)
        if enemy_target is None:
            continue
        gap = pair_distance(u, enemy_target)
        if gap <= 0:
            continue

        # AI rule: if out of charge range (>12") or out of weapon range, advance.
        # Otherwise move normally (keep shooting/charge).
        max_weapon_range = max(
            (w.range_in for w in u.weapons if not w.melee),
            default=0,
        )
        melee_only = all(w.melee for w in u.weapons)
        want_charge = melee_only or (gap <= 12 and not any(w.range_in >= gap for w in u.weapons if not w.melee))

        # Decide move length
        if gap > 12 or (not want_charge and gap > max_weapon_range):
            # Advance
            adv = roll_d6(rng)
            move = min(float(u.movement + adv), gap)
            u.advanced_this_turn = True
            u.moved_this_turn = True
            u.remained_stationary = False
        elif gap > 1:
            # Normal move
            move = min(float(u.movement), gap)
            u.moved_this_turn = True
            u.remained_stationary = False
        else:
            move = 0.0

        u.pos += move
        if verbose and move > 0:
            print(f"    [{current.name}] {u.name} moves {move:.1f}\" (gap now {pair_distance(u, enemy_target):.1f}\")")


def _can_use_strat(force: Force, strat_id: str, round_no: int) -> bool:
    if not force.detachment or strat_id not in force.detachment.stratagems:
        return False
    if force.cp < 1:
        return False
    # Once per phase same strat (simplification).
    if strat_id in force.used_strats_this_phase:
        return False
    return True


def _spend_strat(force: Force, strat_id: str, round_no: int) -> None:
    force.cp -= 1
    force.used_strats_this_phase.add(strat_id)
    force.used_strats_this_round.add((strat_id, round_no))


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
            target = closest_enemy_within(unit, enemy, 8)
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
                dist = pair_distance(unit, target)
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
        target = closest_enemy(unit, enemy)
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
            if pair_distance(unit, e) <= weapon.range_in
        ]
        if not candidates:
            continue
        target = min(candidates, key=lambda e: e.total_wounds)
        dist = pair_distance(unit, target)
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
        # Pick target within 12" declaration range.
        target = closest_enemy_within(unit, enemy, 12)
        if target is None:
            continue
        dist = pair_distance(unit, target)
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
            foe = closest_enemy_within(defender, current, 3)
            if foe is not None:
                _spend_strat(enemy, "HEROIC_INTERVENTION", round_no)
                defender.pos += pair_distance(defender, foe)
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
    dist = pair_distance(charger, target)
    # Overwatch hits on 6+ (5+ with For the Greater Good).
    ow_skill = 5 if target.has_ability("FOR_THE_GREATER_GOOD") else 6
    # STAT-APPROX: we temporarily patch each weapon's BS to ow_skill and fire.
    for weapon in target.weapons:
        if weapon.melee or weapon.range_in < dist:
            continue
        patched = replace(weapon, skill=ow_skill)
        body, char, self_mortals = resolve_shots(target, patched, charger, dist, target_force, rng)
        if self_mortals:
            apply_self_mortals(target, self_mortals)
        deaths = apply_damage_with_attachment(charger, body, char, target_force, charger_force)
        for d in deaths:
            apply_deadly_demise(d, target_force, rng)
        if verbose and (body or char):
            print(f"    [{target_force.name}] OVERWATCH {target.name}->{charger.name} dmg={body}+{char}")


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


def morale_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    current.used_strats_this_phase = set()
    for u in current.units:
        if not u.alive or u.in_reserves:
            continue
        # 11e: Battleshock test if unit is Below Half Strength at end of turn.
        start = u.starting_models or u.models
        below_half = u.models <= (start // 2) if start > 1 else u.total_wounds <= 0
        if below_half:
            # Ld test: 2d6 >= Ld to pass. (We add models_lost_this_round as
            # a crude proxy for 10e's modifier though 11e uses flat 2d6 vs Ld.)
            roll = roll_2d6(rng)
            if roll < u.leadership:
                # Failed — battleshock this round.
                if (
                    not current.insane_bravery_used_this_round
                    and _can_use_strat(current, "INSANE_BRAVERY", round_no)
                ):
                    _spend_strat(current, "INSANE_BRAVERY", round_no)
                    current.insane_bravery_used_this_round = True
                    if verbose:
                        print(f"    [{current.name}] INSANE_BRAVERY saves {u.name}")
                else:
                    u.battleshocked_until_round = round_no
                    if verbose:
                        print(f"    [{current.name}] {u.name} FAILS battleshock (-1 OC, no strats)")
        u.models_lost_this_round = 0


# =========================================================================== #
# Game loop
# =========================================================================== #


def setup_initial_positions(force: Force) -> None:
    """Deploy each unit at its own edge (pos=0), applying Infiltrators/Scouts
    pre-game moves."""
    for u in force.units:
        u.pos = 0.0
        if u.has_ability("INFILTRATORS"):
            # Starts 9" closer to center — subtract from the gap by moving 9".
            u.pos = min(9.0, _BOARD.deployment_gap_in / 2)
        elif u.has_ability("SCOUTS"):
            scouts_n = int(u.abilities["SCOUTS"].get("n", 6))
            u.pos = min(float(scouts_n), _BOARD.deployment_gap_in / 2)


def simulate_game(
    force_a_proto: Force,
    force_b_proto: Force,
    board: Board,
    rounds: int,
    a_goes_first: bool,
    rng: random.Random,
    verbose: bool = False,
) -> str:
    """Returns 'A', 'B', or 'draw'."""
    global _BOARD
    _BOARD = board

    a = force_a_proto.copy()
    b = force_b_proto.copy()
    setup_initial_positions(a)
    setup_initial_positions(b)

    first_force, second_force = (a, b) if a_goes_first else (b, a)

    for rnd in range(1, rounds + 1):
        if not first_force.alive and not second_force.alive:
            break
        if verbose:
            print(f"  == ROUND {rnd} ==")

        for turn_force, turn_enemy in ((first_force, second_force), (second_force, first_force)):
            if not turn_force.alive:
                continue
            if verbose:
                print(f"  -- {turn_force.name} turn --")
            command_phase(turn_force, turn_enemy, rnd, rng, verbose)
            movement_phase(turn_force, turn_enemy, rnd, rng, verbose)
            shooting_phase(turn_force, turn_enemy, rnd, rng, verbose)
            charge_phase(turn_force, turn_enemy, rnd, rng, verbose)
            # Fight phase runs with turn_force considered the "active" player
            # (gets activation priority within tier).
            fight_phase(turn_force, turn_enemy, rnd, rng, verbose)
            morale_phase(turn_force, turn_enemy, rnd, rng, verbose)
            if not turn_enemy.alive:
                break

    # Determine winner
    if a.alive and not b.alive:
        return "A"
    if b.alive and not a.alive:
        return "B"
    if a.total_wounds > b.total_wounds:
        return "A"
    if b.total_wounds > a.total_wounds:
        return "B"
    return "draw"


def simulate_many(
    force_a: Force,
    force_b: Force,
    board: Board,
    sims: int,
    rounds: int,
    a_goes_first: bool,
    seed: int,
) -> dict[str, float]:
    rng = random.Random(seed)
    counts: dict[str, int] = defaultdict(int)
    for _ in range(sims):
        counts[simulate_game(force_a, force_b, board, rounds, a_goes_first, rng)] += 1
    total = sum(counts.values()) or 1
    return {k: counts[k] / total for k in ("A", "B", "draw")}


# =========================================================================== #
# Reporting + CLI
# =========================================================================== #


def pct(f: float) -> str:
    return f"{f * 100:5.1f}%"


def print_report(
    force_a: Force,
    force_b: Force,
    board: Board,
    sims: int,
    rounds: int,
    seed: int,
) -> None:
    res_a_first = simulate_many(force_a, force_b, board, sims, rounds, True, seed)
    res_b_first = simulate_many(force_a, force_b, board, sims, rounds, False, seed + 1)
    blend = {k: (res_a_first[k] + res_b_first[k]) / 2 for k in ("A", "B", "draw")}

    def wounds_summary(f: Force) -> str:
        total = f.total_wounds
        models = sum(u.models for u in f.units)
        units = len(f.units)
        det = f.detachment.name if f.detachment else "no detachment"
        return f"{units} units / {models} models / {total} wound points / {f.cp} CP / {det}"

    print(
        f"\n{force_a.name}  vs  {force_b.name}"
        f"\n  Board: {board.width_in}\"x{board.height_in}\" (gap {board.deployment_gap_in}\")"
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
    parser.add_argument("--sims", type=int, default=5_000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--board-width", type=int, default=44)
    parser.add_argument("--board-height", type=int, default=30)
    parser.add_argument("--deployment-gap", type=int, default=24)
    parser.add_argument("--catalog-dir", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog_dir)
    force_a = load_force(args.force_a, catalog)
    force_b = load_force(args.force_b, catalog)
    board = Board(
        width_in=args.board_width,
        height_in=args.board_height,
        deployment_gap_in=args.deployment_gap,
    )

    if args.verbose:
        rng = random.Random(args.seed)
        res = simulate_game(force_a, force_b, board, args.rounds, True, rng, verbose=True)
        print(f"\nVerbose game result (A goes first): {res}")
        return 0

    print_report(force_a, force_b, board, args.sims, args.rounds, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
