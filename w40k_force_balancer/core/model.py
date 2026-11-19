"""Dataclasses + phase constants.

The primary data model: Catalog (ability/keyword/detachment registry),
Weapon, Unit, Force. Pure dataclasses + a handful of state methods; no
dice, no board, no rule dispatch lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


# Phase constants
PHASE_COMMAND = "COMMAND"
PHASE_MOVEMENT = "MOVEMENT"
PHASE_SHOOTING = "SHOOTING"
PHASE_CHARGE = "CHARGE"
PHASE_FIGHT = "FIGHT"
PHASE_MORALE = "MORALE"
ALL_PHASES = [PHASE_COMMAND, PHASE_MOVEMENT, PHASE_SHOOTING, PHASE_CHARGE, PHASE_FIGHT, PHASE_MORALE]


# =========================================================================== #
# Catalog
# =========================================================================== #


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


# =========================================================================== #
# Battlefield data model
# =========================================================================== #


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
        """A force is alive while ANY unit is alive — including units still
        in deep-strike reserves (finding #2). Previously this excluded
        reserves, which stranded a deep-striker if every on-board unit
        died before arrival: `simulate_game` would short-circuit the
        force as eliminated and never let reserves land."""
        return any(u.alive for u in self.units)

    def has_board_presence(self) -> bool:
        """Stricter check — is anything shootable on the table right now?
        Use this when the phase cares about on-board state (e.g. target
        enumeration), not when deciding whether the force is eliminated."""
        return any(u.alive and not u.in_reserves for u in self.units)

    @property
    def total_wounds(self) -> int:
        """Sum of wound points across ALL alive units including reserves
        (finding #2). Reserves count toward the tiebreak because a force
        with reserves pending is not eliminated."""
        return sum(u.total_wounds for u in self.units)

    def living_on_board(self) -> list[Unit]:
        return [u for u in self.units if u.alive and not u.in_reserves]
