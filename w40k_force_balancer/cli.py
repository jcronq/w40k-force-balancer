"""argparse glue for the Warhammer 40k combat simulator v2."""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Iterable

from .core.board import Board
from .engine.game import simulate_game
from .engine.runner import print_report
from .load.catalog import load_catalog
from .load.force import load_force


CLI_DESCRIPTION = """Warhammer 40k combat simulator v2.

Spatial 1D-collapse model with the full six-phase loop (Command, Movement,
Shooting, Charge, Fight, Morale), weapon + unit + stratagem + detachment
rules, battleshock, and character attachment with Look Out Sir + Precision.

Output shape mirrors v1 — A-first / B-first / 50/50 blend.
"""


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument("force_a", type=Path)
    parser.add_argument("force_b", type=Path)
    parser.add_argument("--sims", type=int, default=5_000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--board-width", type=int, default=44)
    parser.add_argument("--board-height", type=int, default=30)
    parser.add_argument("--deployment-gap", type=int, default=24)
    parser.add_argument("--catalog-dir", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog_dir)
    force_a = load_force(args.force_a, catalog)
    force_b = load_force(args.force_b, catalog)
    board = Board(
        width_in=args.board_width,
        height_in=args.board_height,
        deployment_gap_in=args.deployment_gap,
    )

    if args.verbose:
        rng = random.Random(args.seed)
        res = simulate_game(force_a, force_b, board, args.rounds, True, rng, verbose=True)
        print(f"\nVerbose game result (A goes first): {res}")
        return 0

    print_report(force_a, force_b, board, args.sims, args.rounds, args.seed)
    return 0
