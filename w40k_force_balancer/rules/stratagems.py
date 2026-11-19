"""Stratagem gating + CP spend helpers.

The actual stratagem effects (Fire Overwatch, Rapid Ingress, Heroic
Intervention, Insane Bravery, Command Re-roll, Grenade) fire inline in
the phase modules that trigger them; this module hosts the small shared
gating predicate and the CP-spend side-effect used by every strat.
"""
from __future__ import annotations

from ..core.model import Force


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
