"""Unit abilities — FNP, Deadly Demise, and other squad-level rules.

Deep Strike / Stealth / Fights First / Infiltrators / Scouts / For the
Greater Good / Markerlight are checked inline at the point of use in the
phase and shot-resolution modules — the "ability" is really a boolean
check on `unit.abilities`. This module hosts the small cluster of
helpers that genuinely factor out of their call sites.
"""
from __future__ import annotations

import random

from ..core import board as _board
from ..core.dice import roll_d6
from ..core.model import Force, Unit
from .damage import apply_damage_to_squad


def best_fnp(unit: Unit) -> int | None:
    """Return effective FNP threshold (lower is better), merging native FNP
    field with any FEEL_NO_PAIN ability."""
    native = unit.fnp
    ab = unit.abilities.get("FEEL_NO_PAIN")
    ab_fnp = int(ab.get("n", 5)) if ab else None
    candidates = [v for v in (native, ab_fnp) if v is not None]
    return min(candidates) if candidates else None


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
        return _board.pair_distance(dying, u)
    target = min(candidates, key=pd)
    apply_damage_to_squad(target, n)
