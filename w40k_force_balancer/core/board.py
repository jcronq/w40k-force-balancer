"""Board + 1D-collapse spatial model.

STAT-APPROX: 1D distance collapse — each unit has a scalar `pos` =
inches advanced from its own deployment edge. Left-right drift is
ignored. Impact: no true LoS, no flanking, no pile-in geometry.

The module holds a mutable `_BOARD` global that `simulate_game` sets at
the start of each run. Readers access `_BOARD` indirectly via
`pair_distance` / `get_board`; writers use `set_board` (or just
reassign the attribute on this module).
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Force, Unit


@dataclass
class Board:
    width_in: int = 44
    height_in: int = 30
    deployment_gap_in: int = 24       # inches between the two deployment edges


# Module-level board handle, set by simulate_game before combat starts.
_BOARD = Board()


def set_board(b: Board) -> None:
    """Replace the module-level board. Callers that construct their own
    Board (tests, the game loop) must set it here so `pair_distance`
    picks it up."""
    global _BOARD
    _BOARD = b


def get_board() -> Board:
    return _BOARD


def pair_distance(a: Unit, b: Unit) -> float:
    """Distance in inches between unit a (one force) and unit b (opposing).

    Each unit's `pos` is advance from its own deployment line (0.0 at deploy,
    growing positive as it moves toward enemy). Board.deployment_gap is the
    total inches between the two deployment lines at setup.

    A and B are moving toward each other, so remaining gap = gap - a.pos - b.pos.
    Clamped at 0 (engaged).
    """
    return max(0.0, _BOARD.deployment_gap_in - a.pos - b.pos)


def closest_enemy(unit: Unit, enemy_force: Force) -> Unit | None:
    live = [u for u in enemy_force.living_on_board()]
    if not live:
        return None
    return min(live, key=lambda e: pair_distance(unit, e))


def closest_enemy_within(unit: Unit, enemy_force: Force, max_dist: float) -> Unit | None:
    live = [u for u in enemy_force.living_on_board() if pair_distance(unit, u) <= max_dist]
    if not live:
        return None
    return min(live, key=lambda e: pair_distance(unit, e))
