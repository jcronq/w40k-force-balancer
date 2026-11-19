"""Movement phase: deep-strike arrivals + basic advance / move AI."""
from __future__ import annotations

import random

from ..core import board as _board
from ..core.dice import roll_d6
from ..core.model import Force


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

        # Engaged units can only Fall Back; we don't model fallback choice. Skip.
        if u.engaged_with:
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
