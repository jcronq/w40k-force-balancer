"""Many-sim runner + headline report + doctrine-matrix sweep."""
from __future__ import annotations

import random
from collections import defaultdict
from copy import deepcopy

from ..core.board import Board
from ..core.model import Force
from ..load.doctrines import load_doctrine
from .game import simulate_game


def simulate_many(
    force_a: Force,
    force_b: Force,
    board: Board,
    sims: int,
    rounds: int,
    a_goes_first: bool,
    seed: int,
) -> dict[str, float]:
    rng = random.Random(seed)
    counts: dict[str, int] = defaultdict(int)
    for _ in range(sims):
        counts[simulate_game(force_a, force_b, board, rounds, a_goes_first, rng)] += 1
    total = sum(counts.values()) or 1
    return {k: counts[k] / total for k in ("A", "B", "draw")}


def pct(f: float) -> str:
    return f"{f * 100:5.1f}%"


def print_report(
    force_a: Force,
    force_b: Force,
    board: Board,
    sims: int,
    rounds: int,
    seed: int,
) -> None:
    res_a_first = simulate_many(force_a, force_b, board, sims, rounds, True, seed)
    res_b_first = simulate_many(force_a, force_b, board, sims, rounds, False, seed + 1)
    blend = {k: (res_a_first[k] + res_b_first[k]) / 2 for k in ("A", "B", "draw")}

    def wounds_summary(f: Force) -> str:
        total = f.total_wounds
        models = sum(u.models for u in f.units)
        units = len(f.units)
        det = f.detachment.name if f.detachment else "no detachment"
        return f"{units} units / {models} models / {total} wound points / {f.cp} CP / {det}"

    print(
        f"\n{force_a.name}  vs  {force_b.name}"
        f"\n  Board: {board.width_in}\"x{board.height_in}\" (gap {board.deployment_gap_in}\")"
        f"\n  A: {wounds_summary(force_a)}"
        f"\n  B: {wounds_summary(force_b)}"
        f"\n  {sims:,} sims x {rounds} rounds each\n"
    )
    print(f"  {'':24}  A wins   B wins    draw")
    print(f"  {'A goes first':24}  "
          f"{pct(res_a_first['A'])}  {pct(res_a_first['B'])}  {pct(res_a_first['draw'])}")
    print(f"  {'B goes first':24}  "
          f"{pct(res_b_first['A'])}  {pct(res_b_first['B'])}  {pct(res_b_first['draw'])}")
    print(f"  {'50/50 blend':24}  "
          f"{pct(blend['A'])}  {pct(blend['B'])}  {pct(blend['draw'])}")

    swing = (res_a_first['A'] - res_b_first['A']) * 100
    if abs(swing) >= 1.0:
        print(f"\n  First-turn advantage: {swing:+.1f}pp for A when A goes first")


def _force_with_doctrine(force: Force, doctrine_id: str) -> Force:
    """Return a deepcopy of `force` with every unit's doctrine set to
    `doctrine_id`. Force's own doctrine field is updated to match."""
    f = deepcopy(force)
    doc = load_doctrine(doctrine_id)
    f.doctrine = doc
    for u in f.units:
        u.doctrine = doc
    return f


def simulate_matrix(
    force_a: Force,
    force_b: Force,
    board: Board,
    doctrine_ids: list[str],
    sims: int,
    rounds: int,
    seed: int,
) -> dict[tuple[str, str], dict[str, float]]:
    """Run every (doc_a, doc_b) cell and return a dict keyed by
    (doctrine_a, doctrine_b) -> 50/50-blend {A, B, draw} ratios.
    """
    results: dict[tuple[str, str], dict[str, float]] = {}
    for i, da in enumerate(doctrine_ids):
        fa = _force_with_doctrine(force_a, da)
        for j, db in enumerate(doctrine_ids):
            fb = _force_with_doctrine(force_b, db)
            cell_seed = seed + i * len(doctrine_ids) + j
            r1 = simulate_many(fa, fb, board, sims, rounds, True, cell_seed)
            r2 = simulate_many(fa, fb, board, sims, rounds, False, cell_seed + 100_000)
            blend = {k: (r1[k] + r2[k]) / 2 for k in ("A", "B", "draw")}
            results[(da, db)] = blend
    return results


def print_matrix_report(
    force_a: Force,
    force_b: Force,
    board: Board,
    doctrine_ids: list[str],
    sims: int,
    rounds: int,
    seed: int,
) -> None:
    """Print the doctrine matrix as a grid + summary."""
    results = simulate_matrix(
        force_a, force_b, board, doctrine_ids, sims, rounds, seed,
    )

    print(
        f"\nDOCTRINE MATRIX — {force_a.name} vs {force_b.name}, "
        f"{sims:,} sims per cell"
    )
    print(
        f"  Board: {board.width_in}\"x{board.height_in}\" "
        f"(gap {board.deployment_gap_in}\")"
    )
    print(f"  Cells: A-wins / B-wins / draws (50/50 blend, %)\n")

    cell_w = 16  # width of "XX.X/YY.Y/Z.Z" plus padding
    name_w = max(len(da) for da in doctrine_ids) + 4
    row_label_w = name_w + len("rows: ")
    header = " " * row_label_w + "  " + "".join(d.ljust(cell_w) for d in doctrine_ids)
    print(f"  cols: {force_b.name} doctrine")
    print(f"  rows: {force_a.name} doctrine")
    print()
    print(header)
    print("-" * len(header))
    for da in doctrine_ids:
        row_label = ("rows: " + da).ljust(row_label_w)
        cells = []
        for db in doctrine_ids:
            r = results[(da, db)]
            cells.append(
                f"{r['A']*100:4.1f}/{r['B']*100:4.1f}/{r['draw']*100:3.1f}".ljust(cell_w)
            )
        print(row_label + "  " + "".join(cells))

    # --- Summary ---
    a_wins_per_a_doctrine: dict[str, int] = defaultdict(int)
    a_best_b: dict[str, tuple[str, float]] = {}
    b_best_a: dict[str, tuple[str, float]] = {}
    for (da, db), r in results.items():
        a_wins_per_a_doctrine[da] += 1 if r["A"] > r["B"] else 0
    total_cells = len(doctrine_ids) ** 2
    a_total_wins = sum(1 for r in results.values() if r["A"] > r["B"])
    b_total_wins = sum(1 for r in results.values() if r["B"] > r["A"])

    # For each B doctrine, which A doctrine it does best against (i.e. B's
    # highest win rate across the row of varying A doctrines).
    b_best_cell: dict[str, tuple[str, float]] = {}
    for db in doctrine_ids:
        best = max(doctrine_ids, key=lambda da: results[(da, db)]["B"])
        b_best_cell[db] = (best, results[(best, db)]["B"])

    # And overall: which B doctrine performs best averaged across all A choices.
    b_avg: dict[str, float] = {}
    for db in doctrine_ids:
        avg = sum(results[(da, db)]["B"] for da in doctrine_ids) / len(doctrine_ids)
        b_avg[db] = avg
    best_b_doctrine = max(b_avg, key=b_avg.get)
    # Same from A's perspective.
    a_avg: dict[str, float] = {}
    for da in doctrine_ids:
        avg = sum(results[(da, db)]["A"] for db in doctrine_ids) / len(doctrine_ids)
        a_avg[da] = avg
    best_a_doctrine = max(a_avg, key=a_avg.get)

    print()
    print(
        f"  {force_a.name} wins {a_total_wins}/{total_cells} matchups; "
        f"{force_b.name} wins {b_total_wins}/{total_cells}."
    )
    print(
        f"  {force_a.name}'s best doctrine is {best_a_doctrine} "
        f"({a_avg[best_a_doctrine]*100:.1f}% avg win rate)."
    )
    print(
        f"  {force_b.name}'s best doctrine is {best_b_doctrine} "
        f"({b_avg[best_b_doctrine]*100:.1f}% avg win rate)."
    )
    print()
    print(f"  {force_b.name} doctrine vs best counter:")
    for db in doctrine_ids:
        da, br = b_best_cell[db]
        print(
            f"    {db:12} best when {force_a.name} plays {da:10} "
            f"({br*100:.1f}% B-win)"
        )
