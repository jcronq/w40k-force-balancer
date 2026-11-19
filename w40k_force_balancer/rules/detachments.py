"""Detachment-ability resolvers — Shield Host (Martial Ka'tah), Mont'ka.

The in-combat effect of each detachment ability (e.g. the +1-to-wound
bonus Martial Ka'tah grants, or Mont'ka's extra shooting activation)
fires inline where it applies — resolve_shots and shooting_phase. This
module hosts the per-round *declarations* that the command phase makes,
plus the Rapid Ingress stratagem that fires there too.
"""
from __future__ import annotations

import random

from ..core import board as _board
from ..core.model import Force, Unit
from .stratagems import _can_use_strat, _spend_strat


def declare_martial_katah_target(current: Force, enemy: Force, verbose: bool = False) -> None:
    """Pick closest enemy as the katah target (simple heuristic — bias toward melee)."""
    closest = None
    best_dist = float("inf")
    for u in current.units:
        if not u.alive or u.in_reserves:
            continue
        e = _board.closest_enemy(u, enemy)
        if e is None:
            continue
        d = _board.pair_distance(u, e)
        if d < best_dist:
            best_dist = d
            closest = e
    current.martial_katah_target = closest
    if verbose and closest:
        print(f"    [{current.name}] Martial Ka'tah on {closest.name}")


def declare_montka_target(current: Force, verbose: bool = False) -> None:
    """Pick highest-damage-potential T'au unit as double-shoot target."""
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


def maybe_rapid_ingress(current: Force, round_no: int, verbose: bool = False) -> None:
    """Rapid Ingress (once per game, bring a deep-striker on round 1)."""
    if not (
        round_no == 1
        and not current.rapid_ingress_used
        and current.detachment
        and "RAPID_INGRESS" in current.detachment.stratagems
        and current.cp >= 1
    ):
        return
    for u in current.units:
        if u.in_reserves and u.has_ability("DEEP_STRIKE"):
            u.in_reserves = False
            u.arrived_round = 1
            u.pos = max(0.0, _board.get_board().deployment_gap_in - 9)   # 9" from enemy edge
            current.cp -= 1
            current.rapid_ingress_used = True
            current.used_strats_this_round.add(("RAPID_INGRESS", round_no))
            if verbose:
                print(f"    [{current.name}] Rapid Ingress: {u.name} drops in")
            break
