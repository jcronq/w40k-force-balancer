"""Movement phase: deep-strike arrivals + doctrine-driven move AI.

The movement decision reads the unit's effective doctrine:

  * `doctrine.movement.mode`:
      - `default`       -> old engine heuristic (advance when far, M when close)
      - `advance_toward`-> move M (or M+d6 if advance_roll) toward closest enemy
      - `advance_away`  -> move M (or M+d6) away from closest enemy
      - `stationary`    -> don't move
      - `advance_to_optimal_range` -> maintain half-range window (kite)

  * `doctrine.fall_back.trigger`: `never` / `when_engaged` / `only_if_losing`.

See core/doctrine.py for the catalog.
"""
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


def _losing_the_melee(unit: Unit, enemy_force: Force) -> bool:
    """Finding #5 heuristic: Fall Back when engaged enemies out-throw this
    unit's own melee attacks."""
    partners = [e for e in enemy_force.units if id(e) in unit.engaged_with and e.alive]
    if not partners:
        return False
    incoming = sum(_total_melee_attacks(p) for p in partners)
    outgoing = _total_melee_attacks(unit)
    return incoming > outgoing


def _should_fall_back(unit: Unit, enemy_force: Force) -> bool:
    """Doctrine-aware Fall Back decision."""
    if not unit.engaged_with:
        return False
    trigger = unit.doctrine.fall_back.trigger
    if trigger == "never":
        return False
    if trigger == "when_engaged":
        return True
    # only_if_losing (default engine heuristic)
    return _losing_the_melee(unit, enemy_force)


def _optimal_range(unit: Unit) -> float:
    """Kite target: want to sit at the max half-range among non-melee weapons
    (STAT-APPROX). Melee-only units have no optimal range."""
    half_ranges = [w.range_in / 2 for w in unit.weapons if not w.melee and w.range_in > 0]
    if not half_ranges:
        return 0.0
    return max(half_ranges)


def _apply_movement(
    unit: Unit,
    enemy_target: Unit,
    gap: float,
    rng: random.Random,
) -> None:
    """Execute movement per doctrine.movement.mode. Sets moved_this_turn /
    advanced_this_turn / remained_stationary + mutates unit.pos."""
    mode = unit.doctrine.movement.mode
    advance_roll = unit.doctrine.movement.advance_roll

    if mode == "stationary":
        # Don't move; HEAVY will see remained_stationary=True.
        return

    if mode == "advance_toward":
        # Advance (+d6) only when out of 12" charge range. Within charge
        # range, use plain M so the unit can still shoot + charge this turn
        # (per 11e Advance restriction). This mirrors how a real rush-
        # doctrine player plays: sprint when far, hustle at M when close.
        use_advance = advance_roll and gap > 12
        step = float(unit.movement) + (roll_d6(rng) if use_advance else 0.0)
        move = min(step, gap)
        if move <= 0:
            return
        unit.pos += move
        unit.moved_this_turn = True
        unit.remained_stationary = False
        if use_advance:
            unit.advanced_this_turn = True
        return

    if mode == "advance_away":
        # Backing off doesn't need the Advance action unless yaml says so,
        # and the backward move can't push past our deployment edge.
        step = float(unit.movement) + (roll_d6(rng) if advance_roll else 0.0)
        unit.pos = max(0.0, unit.pos - step)
        unit.moved_this_turn = True
        unit.remained_stationary = False
        if advance_roll:
            unit.advanced_this_turn = True
        return

    if mode == "advance_to_optimal_range":
        optimal = _optimal_range(unit)
        if optimal <= 0:
            # No ranged weapons — fall through to default aggressive behavior
            # so a melee-only "kite" unit still closes rather than sitting still.
            mode = "default"
        else:
            # If gap > optimal, advance (but don't close inside optimal).
            # If gap < optimal, back off to reach optimal. If gap == optimal, stay.
            desired_move = gap - optimal   # positive = forward, negative = backward
            if abs(desired_move) < 1.0:
                return
            step = min(float(unit.movement), abs(desired_move))
            if desired_move > 0:
                unit.pos += step
            else:
                unit.pos = max(0.0, unit.pos - step)
            unit.moved_this_turn = True
            unit.remained_stationary = False
            return

    # --- default heuristic (fallthrough or mode == 'default') ---
    max_weapon_range = max(
        (w.range_in for w in unit.weapons if not w.melee),
        default=0,
    )
    melee_only = all(w.melee for w in unit.weapons)
    want_charge = melee_only or (
        gap <= 12 and not any(w.range_in >= gap for w in unit.weapons if not w.melee)
    )
    if gap > 12 or (not want_charge and gap > max_weapon_range):
        adv = roll_d6(rng)
        move = min(float(unit.movement + adv), gap)
        unit.advanced_this_turn = True
        unit.moved_this_turn = True
        unit.remained_stationary = False
    elif gap > 1:
        move = min(float(unit.movement), gap)
        unit.moved_this_turn = True
        unit.remained_stationary = False
    else:
        return
    unit.pos += move


def movement_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    # Deep-strike arrivals (default round 2, bumped by reserve doctrine)
    for u in current.units:
        if u.in_reserves:
            ds = u.abilities.get("DEEP_STRIKE", {})
            arrival = int(ds.get("arrival_round", 2))
            if round_no >= arrival:
                u.in_reserves = False
                u.arrived_round = round_no
                u.pos = max(0.0, _board.get_board().deployment_gap_in - int(ds.get("range_in", 9)))
                u.moved_this_turn = True
                u.remained_stationary = False
                if verbose:
                    print(f"    [{current.name}] {u.name} deep-strikes in at pos={u.pos:.1f}")

    for u in current.units:
        if not u.alive or u.in_reserves:
            continue
        if u.arrived_round == round_no:
            continue
        u.moved_this_turn = False
        u.advanced_this_turn = False
        u.remained_stationary = True

        # Fall Back check (doctrine-driven).
        if u.engaged_with:
            if _should_fall_back(u, enemy):
                partners = _unit_by_id(enemy, u.engaged_with)
                for p in partners:
                    p.engaged_with.discard(id(u))
                u.engaged_with.clear()
                u.advanced_this_turn = True
                u.moved_this_turn = True
                u.remained_stationary = False
                u.pos = max(0.0, u.pos - float(u.movement))
                if verbose:
                    print(f"    [{current.name}] {u.name} falls back")
            continue

        # Target: closest enemy for distance-reference purposes.
        enemy_target = _board.closest_enemy(u, enemy)
        if enemy_target is None:
            continue
        gap = _board.pair_distance(u, enemy_target)

        pre_pos = u.pos
        _apply_movement(u, enemy_target, gap, rng)
        if verbose and u.pos != pre_pos:
            print(
                f"    [{current.name}] {u.name} moves {u.pos - pre_pos:+.1f}\" "
                f"[{u.doctrine.movement.mode}] (gap now "
                f"{_board.pair_distance(u, enemy_target):.1f}\")"
            )
