"""argparse glue for the Warhammer 40k combat simulator v2."""
from __future__ import annotations

import argparse
import random
from pathlib import Path
from typing import Iterable

from .core.board import Board
from .engine.game import simulate_game
from .engine.runner import print_matrix_report, print_report
from .load.catalog import load_catalog
from .load.doctrines import load_all_doctrines, load_doctrine
from .load.force import load_force


CLI_DESCRIPTION = """Warhammer 40k combat simulator v2.

Spatial 1D-collapse model with the full six-phase loop (Command, Movement,
Shooting, Charge, Fight, Morale), weapon + unit + stratagem + detachment
rules, battleshock, and character attachment with Look Out Sir + Precision.

Output shape mirrors v1 — A-first / B-first / 50/50 blend.

Doctrine options:
  --doctrine-a / --doctrine-b   override a side's doctrine for one run
  --matrix                      run every (doctrine_a, doctrine_b) permutation
                                against each other and print the grid
"""


def _apply_doctrine(force, doctrine_id: str) -> None:
    """In-place swap: set this force's doctrine and every unit's effective
    doctrine to the named one (stripping any unit-level overrides)."""
    doc = load_doctrine(doctrine_id)
    force.doctrine = doc
    for u in force.units:
        u.doctrine = doc


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
    parser.add_argument(
        "--doctrine-a", type=str, default=None,
        help="override A's doctrine (e.g. rush/gunline/kite/hold/reserve)",
    )
    parser.add_argument(
        "--doctrine-b", type=str, default=None,
        help="override B's doctrine",
    )
    parser.add_argument(
        "--matrix", action="store_true",
        help="run every (doctrine_a, doctrine_b) permutation and print the grid",
    )
    parser.add_argument(
        "--matrix-sims", type=int, default=2_000,
        help="sims per matrix cell (default: 2000)",
    )
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog_dir)
    force_a = load_force(args.force_a, catalog)
    force_b = load_force(args.force_b, catalog)
    board = Board(
        width_in=args.board_width,
        height_in=args.board_height,
        deployment_gap_in=args.deployment_gap,
    )

    if args.matrix:
        doctrines = load_all_doctrines()
        # Order the grid so the catalog's starter set appears first.
        order = ["rush", "gunline", "kite", "hold", "reserve"]
        doctrine_ids = [d for d in order if d in doctrines] + sorted(
            d for d in doctrines if d not in order
        )
        if not doctrine_ids:
            print("No doctrines found in catalog/doctrines/.")
            return 1
        print_matrix_report(
            force_a, force_b, board, doctrine_ids,
            sims=args.matrix_sims, rounds=args.rounds, seed=args.seed,
        )
        return 0

    if args.doctrine_a:
        _apply_doctrine(force_a, args.doctrine_a)
    if args.doctrine_b:
        _apply_doctrine(force_b, args.doctrine_b)

    if args.verbose:
        rng = random.Random(args.seed)
        res = simulate_game(force_a, force_b, board, args.rounds, True, rng, verbose=True)
        print(f"\nVerbose game result (A goes first): {res}")
        return 0

    print_report(force_a, force_b, board, args.sims, args.rounds, args.seed)
    return 0
