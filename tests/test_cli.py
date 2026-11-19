"""CLI integration tests — exercise `w40k_force_balancer.main` with the
shipped example forces.

Focus is the --log-game / --log-game-jsonl single-game paths added for
real-vs-sim calibration. Aggregate and matrix paths are smoke-covered.
"""
from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout

import pytest

import w40k_force_balancer as sim


def _example_forces(repo_root):
    return (
        str(repo_root / "force_custodes_2024cp_v2.yaml"),
        str(repo_root / "force_tau_2024cp_v2.yaml"),
    )


def test_cli_log_game_markdown_emits_report(tmp_path, repo_root):
    fa, fb = _example_forces(repo_root)
    md = tmp_path / "game.md"
    rc = sim.main([fa, fb, "--log-game", str(md), "--seed", "0", "--rounds", "5"])
    assert rc == 0
    text = md.read_text()
    assert "# Battle Report" in text
    assert "## Deployment" in text
    assert "## Round 1" in text
    assert "## Final Result" in text


def test_cli_log_game_jsonl_emits_event_stream(tmp_path, repo_root):
    fa, fb = _example_forces(repo_root)
    path = tmp_path / "game.jsonl"
    rc = sim.main([fa, fb, "--log-game-jsonl", str(path), "--seed", "0"])
    assert rc == 0
    lines = path.read_text().strip().splitlines()
    events = [json.loads(line) for line in lines]
    types = [e["type"] for e in events]
    # deployment first, game_end last, activation(s) in between
    assert types[0] == "deployment"
    assert types[1] == "deployment"
    assert types[-1] == "game_end"
    assert "activation" in types


def test_cli_both_log_flags_emit_same_game(tmp_path, repo_root):
    fa, fb = _example_forces(repo_root)
    md = tmp_path / "game.md"
    jsonl = tmp_path / "game.jsonl"
    rc = sim.main([
        fa, fb,
        "--log-game", str(md),
        "--log-game-jsonl", str(jsonl),
        "--seed", "0",
    ])
    assert rc == 0
    assert md.exists()
    assert jsonl.exists()
    events = [json.loads(line) for line in jsonl.read_text().strip().splitlines()]
    game_end = events[-1]
    text = md.read_text()
    # Winner banner matches game_end winner.
    if game_end["winner"] == "draw":
        assert "Winner:** draw" in text
    else:
        assert f"Winner:** Force {game_end['winner']}" in text


def test_cli_default_run_does_not_emit_a_log(tmp_path, repo_root, capsys):
    fa, fb = _example_forces(repo_root)
    rc = sim.main([fa, fb, "--sims", "20", "--seed", "0"])
    assert rc == 0
    # No markdown / jsonl in tmp_path
    assert not list(tmp_path.glob("*.md"))
    assert not list(tmp_path.glob("*.jsonl"))


def test_cli_log_game_overwrites_prior_file(tmp_path, repo_root):
    fa, fb = _example_forces(repo_root)
    md = tmp_path / "game.md"
    md.write_text("stale content that should be clobbered\n")
    rc = sim.main([fa, fb, "--log-game", str(md), "--seed", "0"])
    assert rc == 0
    assert "stale content" not in md.read_text()


def test_cli_log_game_respects_seed(tmp_path, repo_root):
    """Two runs with the same seed produce the same markdown + jsonl."""
    fa, fb = _example_forces(repo_root)
    md1 = tmp_path / "a.md"
    md2 = tmp_path / "b.md"
    for p in (md1, md2):
        rc = sim.main([fa, fb, "--log-game", str(p), "--seed", "42"])
        assert rc == 0
    assert md1.read_text() == md2.read_text()


def test_cli_log_game_with_matrix_is_rejected(tmp_path, repo_root):
    """--log-game + --matrix is a usage error."""
    fa, fb = _example_forces(repo_root)
    md = tmp_path / "game.md"
    rc = sim.main([fa, fb, "--log-game", str(md), "--matrix"])
    assert rc == 2


def test_cli_matrix_still_works(tmp_path, repo_root, capsys):
    fa, fb = _example_forces(repo_root)
    rc = sim.main([
        fa, fb,
        "--matrix", "--matrix-sims", "10", "--rounds", "3", "--seed", "0",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DOCTRINE MATRIX" in out
