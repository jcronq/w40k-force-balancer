"""Movement phase: deep-strike arrivals + basic advance / move AI."""
from __future__ import annotations

import random

from ..core import board as _board
from ..core.dice import roll_d6
from ..core.model import Force, Unit


def _unit_by_id(force: Force, ids: set[int]) -> list[Unit]:
    return [u for u in force.units if id(u) in ids]


def _total_melee_attacks(unit: Unit) -> int:
    """Simple heuristic: sum of A x models across melee weapons."""
    return sum(w.attacks * unit.models for w in unit.weapons if w.melee)


def _should_fall_back(unit: Unit, enemy_force: Force) -> bool:
    """Fall Back when engaged enemies out-throw this unit in melee.

    Heuristic per finding #5: compare total melee attacks from engaged
    enemies vs this unit's own melee attack count. Attacks (not expected
    damage) are the user-specified proxy — keeps the decision fully
    deterministic and matches a real player's "they'll kill more of me
    than I can kill back" instinct without re-simulating the fight.
    """
    partners = [e for e in enemy_force.units if id(e) in unit.engaged_with and e.alive]
    if not partners:
        return False
    incoming = sum(_total_melee_attacks(p) for p in partners)
    outgoing = _total_melee_attacks(unit)
    return incoming > outgoing


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
                u.pos = max(0.0, _board.get_board().deployment_gap_in - int(ds.get("range_in", 9)))
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

        # Engaged units may Fall Back (finding #5). Decision heuristic:
        # if the engaged enemies pointing melee attacks at this unit out-
        # throw this unit's melee attacks back at them, Fall Back.
        # Fall Back clears engagement, marks advanced_this_turn=True, and
        # blocks Shooting + Charge this turn. Deterministic given state.
        if u.engaged_with:
            if _should_fall_back(u, enemy):
                partners = _unit_by_id(enemy, u.engaged_with)
                for p in partners:
                    p.engaged_with.discard(id(u))
                u.engaged_with.clear()
                u.advanced_this_turn = True
                u.moved_this_turn = True
                u.remained_stationary = False
                # Pull back slightly so next phases see them as off-engaged.
                u.pos = max(0.0, u.pos - float(u.movement))
                if verbose:
                    print(f"    [{current.name}] {u.name} falls back")
            continue

        # Target: closest enemy.
        enemy_target = _board.closest_enemy(u, enemy)
        if enemy_target is None:
            continue
        gap = _board.pair_distance(u, enemy_target)
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
            print(f"    [{current.name}] {u.name} moves {move:.1f}\" (gap now {_board.pair_distance(u, enemy_target):.1f}\")")
