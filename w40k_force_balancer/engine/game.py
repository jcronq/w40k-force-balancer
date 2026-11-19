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
    logger.record({
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
    })


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

    first_player = "A" if a_goes_first else "B"
    _emit_deployment(logger, a, "A", board, first_player, seed)
    _emit_deployment(logger, b, "B", board, first_player, seed)

    first_force, second_force = (a, b) if a_goes_first else (b, a)
    first_side = "A" if a_goes_first else "B"
    second_side = "B" if a_goes_first else "A"

    reason = "max rounds reached"
    rnd = 0

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

        logger.record({
            "round": rnd,
            "phase": "end",
            "type": "round_end",
        })
        if not a.alive or not b.alive:
            break

    # Determine winner
    if a.alive and not b.alive:
        winner = "A"
    elif b.alive and not a.alive:
        winner = "B"
    elif a.total_wounds > b.total_wounds:
        winner = "A"
        reason = "A had more remaining wounds"
    elif b.total_wounds > a.total_wounds:
        winner = "B"
        reason = "B had more remaining wounds"
    else:
        winner = "draw"
        reason = "tied wounds remaining"

    logger.record({
        "round": rnd,
        "phase": "end",
        "type": "game_end",
        "winner": winner,
        "reason": reason,
        "remaining_wounds_a": a.total_wounds,
        "remaining_wounds_b": b.total_wounds,
        "first_player": first_player,
    })

    return winner
