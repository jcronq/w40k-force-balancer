"""Warhammer 40k combat simulator v2 — package root.

Scope (v2, per Jason 2026-11-18):
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

STAT-APPROX flags on every expected-value shortcut; grep the modules to audit.

Statistical approximations active in this sim (fidelity shortcuts):
  1. 1D distance collapse — see `core/board.py`.
  2. Grenade stratagem — samples 1d6 per use (expected value 3.5) —
     see `phases/shooting.py`.
  3. Overwatch applies the strat universally — see `phases/charge.py`.
  4. Devastating Wound damage does not get further FNP ignore rolls —
     see `rules/weapon_abilities.py`.
  5. Fall Back heuristic (count-of-attacks, not expected damage) —
     see `phases/movement.py`.

Promoted from STAT-APPROX to full fidelity on 2026-11-18 by the
adversarial-review fix pass:
  * Independent-rolls save approximation (fixed upstream before the
    package split).
  * Precision character allocation — now per-hit Bernoulli, not
    ceil(n/2) (finding #6).
  * Markerlight re-roll — now a real re-roll in the hit loop, not a
    BS patch clamped at 2+ (finding #3).
  * Per-attack damage — overkill from a single attack no longer flows
    through the squad (finding #1).

Public API:
    load_catalogs(catalog_dir=None) -> Catalog
    load_force(path, catalog) -> Force
    run_simulation(force_a, force_b, board, sims, rounds, a_goes_first, seed) -> dict
    main(argv=None) -> int                          # the CLI entrypoint
"""
from __future__ import annotations

# --- Core primitives -----------------------------------------------------
from .core import board as _board_mod
from .core.board import (
    Board,
    closest_enemy,
    closest_enemy_within,
    get_board,
    pair_distance,
    set_board,
)
from .core.dice import clamp, roll_2d6, roll_d6, to_wound_threshold
from .core.model import (
    ALL_PHASES,
    PHASE_CHARGE,
    PHASE_COMMAND,
    PHASE_FIGHT,
    PHASE_MORALE,
    PHASE_MOVEMENT,
    PHASE_SHOOTING,
    Catalog,
    CatalogEntry,
    Detachment,
    Force,
    Unit,
    Weapon,
)

# --- Loaders --------------------------------------------------------------
from .load.catalog import CATALOG_DIR_DEFAULT, load_catalog
from .load.force import load_force

# --- Rule implementations ------------------------------------------------
from .rules.damage import (
    ShotResult,
    apply_damage_to_squad,
    apply_damage_with_attachment,
    apply_self_mortals,
    apply_self_mortals_rng,
)
from .rules.stratagems import _can_use_strat, _spend_strat
from .rules.unit_abilities import apply_deadly_demise, best_fnp
from .rules.weapon_abilities import resolve_shots

# --- Phases ---------------------------------------------------------------
from .phases.charge import _do_overwatch, charge_phase
from .phases.command import command_phase
from .phases.fight import _fight_activation, fight_phase
from .phases.morale import morale_phase
from .phases.movement import movement_phase
from .phases.shooting import _shoot_weapon_set, shooting_phase

# --- Engine + CLI ---------------------------------------------------------
from .cli import main
from .engine.game import setup_initial_positions, simulate_game
from .engine.runner import pct, print_report, simulate_many


# Public API aliases (spec: load_catalogs / run_simulation).
load_catalogs = load_catalog
run_simulation = simulate_many


# Module-level `_BOARD` read-through for callers that treat this package
# like the old monolith. For writes, use `set_board(b)` — module
# `__setattr__` is not a thing, so reassigning `w40k_force_balancer._BOARD`
# on the package module would NOT propagate to `core.board._BOARD`.
def __getattr__(name):
    if name == "_BOARD":
        return _board_mod._BOARD
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Public API
    "load_catalogs",
    "load_force",
    "run_simulation",
    "main",
    # Core
    "Board",
    "Catalog",
    "CatalogEntry",
    "Detachment",
    "Force",
    "Unit",
    "Weapon",
    "set_board",
    "get_board",
    "pair_distance",
    "closest_enemy",
    "closest_enemy_within",
    "roll_d6",
    "roll_2d6",
    "clamp",
    "to_wound_threshold",
    # Rules
    "resolve_shots",
    "best_fnp",
    "apply_damage_to_squad",
    "apply_damage_with_attachment",
    "apply_self_mortals",
    "apply_self_mortals_rng",
    "apply_deadly_demise",
    "ShotResult",
    # Phases
    "command_phase",
    "movement_phase",
    "shooting_phase",
    "charge_phase",
    "fight_phase",
    "morale_phase",
    # Engine
    "setup_initial_positions",
    "simulate_game",
    "simulate_many",
    "print_report",
    # Constants
    "ALL_PHASES",
    "PHASE_COMMAND",
    "PHASE_MOVEMENT",
    "PHASE_SHOOTING",
    "PHASE_CHARGE",
    "PHASE_FIGHT",
    "PHASE_MORALE",
    "CATALOG_DIR_DEFAULT",
]
