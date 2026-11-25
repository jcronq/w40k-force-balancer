"""Unit tests for the BattleLogger protocol + implementations.

Game-engine wiring is covered in test_game_logging; this file sticks to
the renderers and fan-out semantics.
"""
from __future__ import annotations

import io
import json

import pytest

from w40k_force_balancer.engine.logger import (
    JsonlLogger,
    MarkdownLogger,
    MultiLogger,
    NullLogger,
    VerboseStdoutLogger,
    _render_markdown,
)


def _deployment_event():
    return {
        "round": 0,
        "phase": "deployment",
        "type": "deployment",
        "force": "A",
        "force_name": "Custodes",
        "board_width": 44,
        "board_height": 30,
        "deployment_gap": 24,
        "seed": 0,
        "first_player": "A",
        "units": [
            {"name": "Blade Champion", "pos": 0.0, "models": 1, "wounds": 6}
        ],
        "reserves": [
            {"name": "Allarus Custodians", "models": 3, "wounds": 12}
        ],
    }


def _deployment_event_b():
    return {
        "round": 0,
        "phase": "deployment",
        "type": "deployment",
        "force": "B",
        "force_name": "T'au",
        "units": [
            {"name": "Breacher Team", "pos": 0.0, "models": 10, "wounds": 10}
        ],
        "reserves": [],
    }


def _activation_event():
    return {
        "round": 1,
        "turn": "A",
        "phase": "shooting",
        "type": "activation",
        "actor": "Custodian Guard",
        "target": "Breacher Team",
        "weapon": "Guardian spear (ranged)",
        "attacks": 10,
        "hits": 8,
        "wounds": 6,
        "unsaved": 4,
        "damage": 8,
        "models_killed": 4,
        "attached_character_damage": 0,
    }


def _game_end_event():
    return {
        "round": 4,
        "phase": "end",
        "type": "game_end",
        "winner": "A",
        "reason": "B wiped",
        "remaining_wounds_a": 18,
        "remaining_wounds_b": 0,
        "first_player": "A",
    }


def test_null_logger_is_noop():
    logger = NullLogger()
    logger.record(_activation_event())
    logger.finalize()  # must not raise


def test_jsonl_logger_writes_line_per_event(tmp_path):
    path = tmp_path / "game.jsonl"
    with JsonlLogger(path) as logger:
        logger.record(_deployment_event())
        logger.record(_activation_event())
        logger.record(_game_end_event())

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["type"] == "deployment"
    assert parsed[1]["type"] == "activation"
    assert parsed[2]["type"] == "game_end"
    # Keys are sorted for stable diffs
    assert list(parsed[1].keys()) == sorted(parsed[1].keys())


def test_jsonl_logger_overwrites_prior_contents(tmp_path):
    path = tmp_path / "game.jsonl"
    path.write_text("stale line 1\nstale line 2\n")
    with JsonlLogger(path) as logger:
        logger.record(_deployment_event())
    text = path.read_text()
    assert "stale" not in text
    assert "deployment" in text


def test_markdown_logger_writes_human_readable_report(tmp_path):
    path = tmp_path / "game.md"
    with MarkdownLogger(path) as logger:
        logger.record(_deployment_event())
        logger.record(_deployment_event_b())
        logger.record(_activation_event())
        logger.record(_game_end_event())

    text = path.read_text()
    assert "# Battle Report — Custodes vs T'au" in text
    assert "## Deployment" in text
    assert "## Round 1 — A Turn" in text
    assert "### Shooting Phase" in text
    # Body of the activation row
    assert "10 attacks" in text
    assert "4 model(s) killed" in text
    assert "## Final Result" in text
    assert "Force A" in text


def test_markdown_renderer_handles_empty_stream():
    text = _render_markdown([])
    assert text.startswith("# Battle Report")


def test_multi_logger_fans_out(tmp_path):
    md = MarkdownLogger(tmp_path / "game.md")
    jsonl = JsonlLogger(tmp_path / "game.jsonl")
    multi = MultiLogger([md, jsonl])
    multi.record(_deployment_event())
    multi.record(_activation_event())
    multi.record(_game_end_event())
    multi.finalize()

    jsonl_lines = (tmp_path / "game.jsonl").read_text().strip().splitlines()
    assert len(jsonl_lines) == 3
    md_text = (tmp_path / "game.md").read_text()
    assert "# Battle Report" in md_text


def test_verbose_logger_writes_to_stream():
    buf = io.StringIO()
    logger = VerboseStdoutLogger(buf)
    logger.record(_deployment_event())
    logger.record(_activation_event())
    logger.record(_game_end_event())
    logger.finalize()
    out = buf.getvalue()
    assert "[deploy]" in out
    assert "r1 A shooting" in out
    assert "[game_end]" in out
