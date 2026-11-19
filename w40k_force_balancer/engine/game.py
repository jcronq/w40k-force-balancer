"""Single-game orchestrator: setup, phase loop, winner determination."""
from __future__ import annotations

import random

from ..core import board as _board
from ..core.board import Board
from ..core.model import Force
from ..phases.charge import charge_phase
from ..phases.command import command_phase
from ..phases.fight import fight_phase
from ..phases.morale import morale_phase
from ..phases.movement import movement_phase
from ..phases.shooting import shooting_phase


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


def simulate_game(
    force_a_proto: Force,
    force_b_proto: Force,
    board: Board,
    rounds: int,
    a_goes_first: bool,
    rng: random.Random,
    verbose: bool = False,
) -> str:
    """Returns 'A', 'B', or 'draw'."""
    _board.set_board(board)

    a = force_a_proto.copy()
    b = force_b_proto.copy()
    setup_initial_positions(a)
    setup_initial_positions(b)

    first_force, second_force = (a, b) if a_goes_first else (b, a)

    for rnd in range(1, rounds + 1):
        if not first_force.alive and not second_force.alive:
            break
        if verbose:
            print(f"  == ROUND {rnd} ==")

        for turn_force, turn_enemy in ((first_force, second_force), (second_force, first_force)):
            if not turn_force.alive:
                continue
            if verbose:
                print(f"  -- {turn_force.name} turn --")
            command_phase(turn_force, turn_enemy, rnd, rng, verbose)
            movement_phase(turn_force, turn_enemy, rnd, rng, verbose)
            shooting_phase(turn_force, turn_enemy, rnd, rng, verbose)
            charge_phase(turn_force, turn_enemy, rnd, rng, verbose)
            # Fight phase runs with turn_force considered the "active" player
            # (gets activation priority within tier).
            fight_phase(turn_force, turn_enemy, rnd, rng, verbose)
            morale_phase(turn_force, turn_enemy, rnd, rng, verbose)
            if not turn_enemy.alive:
                break

    # Determine winner
    if a.alive and not b.alive:
        return "A"
    if b.alive and not a.alive:
        return "B"
    if a.total_wounds > b.total_wounds:
        return "A"
    if b.total_wounds > a.total_wounds:
        return "B"
    return "draw"
