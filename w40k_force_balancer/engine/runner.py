"""Many-sim runner + headline report."""
from __future__ import annotations

import random
from collections import defaultdict

from ..core.board import Board
from ..core.model import Force
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
