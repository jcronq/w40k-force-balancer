"""Integration + matrix tests — doctrines change outcomes and the matrix prints."""
from __future__ import annotations

import io
import contextlib

import w40k_force_balancer as sim
from w40k_force_balancer.engine.runner import (
    print_matrix_report,
    simulate_matrix,
    simulate_many,
)
from w40k_force_balancer.load.doctrines import load_doctrine


def _load_pair(repo_root, catalog):
    fa = sim.load_force(repo_root / "forces" / "force_custodes_2024cp_v2.yaml", catalog)
    fb = sim.load_force(repo_root / "forces" / "force_tau_2024cp_v2.yaml", catalog)
    return fa, fb


def _with_doctrine(force, doctrine_id):
    """In-place: set every unit's doctrine to the named one."""
    from copy import deepcopy
    f = deepcopy(force)
    doc = load_doctrine(doctrine_id)
    f.doctrine = doc
    for u in f.units:
        u.doctrine = doc
    return f


def test_doctrine_change_changes_outcome(repo_root, catalog, board_default):
    """Smoke: Custodes-rush-vs-Tau-gunline and Custodes-rush-vs-Tau-kite
    produce different win rates."""
    fa, fb = _load_pair(repo_root, catalog)
    fa_rush = _with_doctrine(fa, "rush")
    fb_gun = _with_doctrine(fb, "gunline")
    fb_kite = _with_doctrine(fb, "kite")

    r_vs_gun = simulate_many(fa_rush, fb_gun, board_default, 200, 5, True, seed=1)
    r_vs_kite = simulate_many(fa_rush, fb_kite, board_default, 200, 5, True, seed=1)

    assert abs(r_vs_gun["A"] - r_vs_kite["A"]) > 0.05, (
        f"Doctrines should materially shift the win rate; got "
        f"gun={r_vs_gun['A']:.3f} vs kite={r_vs_kite['A']:.3f}"
    )


def test_matrix_sweep_fills_every_cell(repo_root, catalog, board_default):
    fa, fb = _load_pair(repo_root, catalog)
    ids = ["rush", "gunline", "kite", "hold", "reserve"]
    results = simulate_matrix(fa, fb, board_default, ids, sims=100, rounds=5, seed=0)
    assert len(results) == 25
    for (da, db), r in results.items():
        assert da in ids and db in ids
        total = r["A"] + r["B"] + r["draw"]
        assert 0.99 <= total <= 1.01   # probabilities sum to 1


def test_print_matrix_prints_grid(repo_root, catalog, board_default, capsys):
    fa, fb = _load_pair(repo_root, catalog)
    ids = ["rush", "gunline", "kite", "hold", "reserve"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_matrix_report(
            fa, fb, board_default, ids,
            sims=50, rounds=5, seed=0,
        )
    out = buf.getvalue()
    assert "DOCTRINE MATRIX" in out
    for d in ids:
        assert d in out
    assert "best doctrine" in out.lower()
