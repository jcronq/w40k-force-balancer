"""Stratagem gating + CP spend helpers.

The actual stratagem effects (Fire Overwatch, Rapid Ingress, Heroic
Intervention, Insane Bravery, Command Re-roll, Grenade) fire inline in
the phase modules that trigger them; this module hosts the small shared
gating predicate and the CP-spend side-effect used by every strat.

11e stratagem gates (finding #10):
  * Once per phase for the same strat (friendly side).
  * Once per turn per target unit for the same strat — a strat that
    targets the SAME unit twice in one turn across different phases is
    denied the second time. Pass the target unit through
    `_can_use_strat` / `_spend_strat` to activate this gate; the shim
    without a `unit` arg keeps strats that don't target a specific unit
    (Insane Bravery, Command Re-roll on a dice pool) working as before.
"""
from __future__ import annotations

from ..core.model import Force, Unit


def _can_use_strat(
    force: Force,
    strat_id: str,
    round_no: int,
    unit: Unit | None = None,
) -> bool:
    if not force.detachment or strat_id not in force.detachment.stratagems:
        return False
    if force.cp < 1:
        return False
    # Once per phase same strat (simplification).
    if strat_id in force.used_strats_this_phase:
        return False
    # Once per turn per unit: a strat that targets a specific unit can't
    # be fired on that unit again in the same turn, even across phases.
    if unit is not None:
        key = (strat_id, id(unit), round_no)
        if key in force.used_strats_this_turn_per_unit:
            return False
    return True


def _spend_strat(
    force: Force,
    strat_id: str,
    round_no: int,
    unit: Unit | None = None,
) -> None:
    force.cp -= 1
    force.used_strats_this_phase.add(strat_id)
    force.used_strats_this_round.add((strat_id, round_no))
    if unit is not None:
        force.used_strats_this_turn_per_unit.add((strat_id, id(unit), round_no))
