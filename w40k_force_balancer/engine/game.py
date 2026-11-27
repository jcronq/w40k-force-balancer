"""Single-game orchestrator: setup, phase loop, winner determination."""
from __future__ import annotations

import random

from ..core import board as _board
from ..core.board import Board
from ..core.model import Force, Unit
from ..phases.charge import charge_phase
from ..phases.command import command_phase
from ..phases.fight import fight_phase
from ..phases.morale import morale_phase
from ..phases.movement import movement_phase
from ..phases.shooting import shooting_phase
from .logger import (
    BattleLogger,
    NullLogger,
    VerboseStdoutLogger,
)


# ---------------------------------------------------------------------------
# Mission / scoring constants (minimal 10e Chapter Approved VP model).
# ---------------------------------------------------------------------------
#
# The 1D-collapse board can't place objectives on both axes, so we project
# three markers onto the approach axis at gap/4, gap/2, 3*gap/4 — a center
# marker and two "flank" markers 12" away from center for the default 24"
# gap. A unit holds an objective if it's within 3" AND alive AND on the
# board; whichever side has more OC on a marker at round-end holds it and
# scores OBJECTIVE_HOLD_VP (= 5 VP, the 10e primary rate). Tabling is an
# instant win; the old total_wounds tiebreaker only decides exact VP ties.
OBJECTIVE_HOLD_VP = 5
OBJECTIVE_RADIUS = 3.0


def _default_objectives(board: Board) -> list[float]:
    """Three marker positions along the approach axis, in inches from A's
    deployment edge. Center + two flanks offset 6" (gap/4) either side."""
    gap = float(board.deployment_gap_in)
    return [gap / 4.0, gap / 2.0, 3.0 * gap / 4.0]


def _unit_pos_from_a(u: Unit, is_side_a: bool, gap: float) -> float:
    """Project a unit's own-edge-relative pos onto the shared A-edge axis."""
    return u.pos if is_side_a else (gap - u.pos)


def _oc_contribution(
    u: Unit,
    obj_pos_a: float,
    is_side_a: bool,
    gap: float,
) -> int:
    if not u.alive or u.in_reserves:
        return 0
    unit_pos_from_a = _unit_pos_from_a(u, is_side_a, gap)
    if abs(unit_pos_from_a - obj_pos_a) > OBJECTIVE_RADIUS:
        return 0
    return u.oc * u.models


def _score_round(
    a: Force,
    b: Force,
    objectives: list[float],
    gap: float,
) -> tuple[int, int, list[dict]]:
    """Compute per-objective holder + VP for this round. Returns
    (a_round_vp, b_round_vp, per_obj_details)."""
    a_vp = 0
    b_vp = 0
    details: list[dict] = []
    for obj_pos_a in objectives:
        a_oc = sum(_oc_contribution(u, obj_pos_a, True, gap) for u in a.units)
        b_oc = sum(_oc_contribution(u, obj_pos_a, False, gap) for u in b.units)
        if a_oc > b_oc:
            a_vp += OBJECTIVE_HOLD_VP
            holder = "A"
        elif b_oc > a_oc:
            b_vp += OBJECTIVE_HOLD_VP
            holder = "B"
        else:
            holder = "contested"
        details.append({
            "pos": obj_pos_a,
            "a_oc": a_oc,
            "b_oc": b_oc,
            "holder": holder,
        })
    return a_vp, b_vp, details


def setup_initial_positions(force: Force) -> None:
    """Deploy each unit at its own edge (pos=0), applying Infiltrators/Scouts
    pre-game moves."""
    board = _board.get_board()
    for u in force.units:
        u.pos = 0.0
        if u.has_ability("INFILTRATORS"):
            # Starts 9" closer to center — subtract from the gap by moving 9".
            u.pos = min(9.0, board.deployment_gap_in / 2)
        elif u.has_ability("SCOUTS"):
            scouts_n = int(u.abilities["SCOUTS"].get("n", 6))
            u.pos = min(float(scouts_n), board.deployment_gap_in / 2)


def _unit_snapshot(u: Unit) -> dict:
    return {
        "name": u.name,
        "models": u.models,
        "wounds": u.total_wounds,
        "pos": u.pos,
    }


def _emit_deployment(
    logger: BattleLogger,
    force: Force,
    side: str,
    board: Board,
    first_player: str,
    seed: int | None,
    objectives: list[float] | None = None,
) -> None:
    on_board: list[dict] = []
    reserves: list[dict] = []
    for u in force.units:
        snap = _unit_snapshot(u)
        if u.attached_to is not None:
            snap["leader_of"] = u.attached_to.name
        if u.attached_character is not None:
            snap["attached_character"] = u.attached_character.name
        if u.in_reserves:
            reserves.append({
                "name": u.name,
                "models": u.models,
                "wounds": u.total_wounds,
            })
        else:
            on_board.append(snap)
    event = {
        "round": 0,
        "phase": "deployment",
        "type": "deployment",
        "force": side,
        "force_name": force.name,
        "units": on_board,
        "reserves": reserves,
        "board_width": board.width_in,
        "board_height": board.height_in,
        "deployment_gap": board.deployment_gap_in,
        "first_player": first_player,
        "seed": seed,
    }
    if objectives is not None:
        event["objectives"] = list(objectives)
    logger.record(event)


def simulate_game(
    force_a_proto: Force,
    force_b_proto: Force,
    board: Board,
    rounds: int,
    a_goes_first: bool,
    rng: random.Random,
    verbose: bool = False,
    logger: BattleLogger | None = None,
    seed: int | None = None,
) -> str:
    """Returns 'A', 'B', or 'draw'.

    Scoring model (10e Chapter Approved minimum viable):
      * 3 objectives at gap/4, gap/2, 3*gap/4 along the 1D approach axis.
      * Round-end: each objective awards 5 VP to the side with greater OC
        within 3" (ties = contested, no VP).
      * Tabling (opposing force fully eliminated) = instant win.
      * At end of round `rounds`, higher VP wins. Exact VP tie falls back
        to the legacy total_wounds tiebreaker.

    `logger` — optional BattleLogger. Defaults to NullLogger when verbose
    is off; when verbose is True, defaults to a VerboseStdoutLogger so
    the old decision-trace behaviour is preserved. Pass a logger
    explicitly to capture markdown / jsonl output.
    """
    _board.set_board(board)
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()

    a = force_a_proto.copy()
    b = force_b_proto.copy()
    setup_initial_positions(a)
    setup_initial_positions(b)

    objectives = _default_objectives(board)
    gap = float(board.deployment_gap_in)

    first_player = "A" if a_goes_first else "B"
    _emit_deployment(logger, a, "A", board, first_player, seed, objectives)
    _emit_deployment(logger, b, "B", board, first_player, seed, objectives)

    first_force, second_force = (a, b) if a_goes_first else (b, a)
    first_side = "A" if a_goes_first else "B"
    second_side = "B" if a_goes_first else "A"

    reason = "max rounds reached"
    rnd = 0
    a_vp = 0
    b_vp = 0

    for rnd in range(1, rounds + 1):
        if not first_force.alive and not second_force.alive:
            reason = "mutual elimination"
            break

        for turn_force, turn_enemy, turn_side in (
            (first_force, second_force, first_side),
            (second_force, first_force, second_side),
        ):
            if not turn_force.alive:
                continue
            command_phase(turn_force, turn_enemy, rnd, rng,
                          verbose=False, logger=logger, turn_side=turn_side)
            movement_phase(turn_force, turn_enemy, rnd, rng,
                           verbose=False, logger=logger, turn_side=turn_side)
            shooting_phase(turn_force, turn_enemy, rnd, rng,
                           verbose=False, logger=logger, turn_side=turn_side)
            charge_phase(turn_force, turn_enemy, rnd, rng,
                         verbose=False, logger=logger, turn_side=turn_side,
                         enemy_side=("B" if turn_side == "A" else "A"))
            fight_phase(turn_force, turn_enemy, rnd, rng,
                        verbose=False, logger=logger, turn_side=turn_side,
                        enemy_side=("B" if turn_side == "A" else "A"))
            morale_phase(turn_force, turn_enemy, rnd, rng,
                         verbose=False, logger=logger, turn_side=turn_side)
            if not turn_enemy.alive:
                reason = f"{'B' if turn_enemy is b else 'A'} wiped"
                break

        # End-of-round primary scoring.
        round_a_vp, round_b_vp, per_obj = _score_round(a, b, objectives, gap)
        a_vp += round_a_vp
        b_vp += round_b_vp
        logger.record({
            "round": rnd,
            "phase": "end",
            "type": "primary_score",
            "a_vp_this_round": round_a_vp,
            "b_vp_this_round": round_b_vp,
            "a_vp_total": a_vp,
            "b_vp_total": b_vp,
            "objectives": per_obj,
        })

        logger.record({
            "round": rnd,
            "phase": "end",
            "type": "round_end",
        })
        if not a.alive or not b.alive:
            break

    # Determine winner — tabling first, then VP, then wounds.
    if a.alive and not b.alive:
        winner = "A"
        reason = "B tabled"
    elif b.alive and not a.alive:
        winner = "B"
        reason = "A tabled"
    elif a_vp > b_vp:
        winner = "A"
        reason = f"A won on primary VP ({a_vp} vs {b_vp})"
    elif b_vp > a_vp:
        winner = "B"
        reason = f"B won on primary VP ({b_vp} vs {a_vp})"
    elif a.total_wounds > b.total_wounds:
        winner = "A"
        reason = f"VP tied {a_vp}-{b_vp}; A had more remaining wounds"
    elif b.total_wounds > a.total_wounds:
        winner = "B"
        reason = f"VP tied {a_vp}-{b_vp}; B had more remaining wounds"
    else:
        winner = "draw"
        reason = f"VP + wounds both tied ({a_vp}-{b_vp})"

    logger.record({
        "round": rnd,
        "phase": "end",
        "type": "game_end",
        "winner": winner,
        "reason": reason,
        "remaining_wounds_a": a.total_wounds,
        "remaining_wounds_b": b.total_wounds,
        "a_vp": a_vp,
        "b_vp": b_vp,
        "first_player": first_player,
    })

    return winner
