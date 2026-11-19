"""Doctrine loader tests — catalog parse, unit override, validation."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from w40k_force_balancer.core.doctrine import DEFAULT_DOCTRINE, Doctrine
from w40k_force_balancer.load.doctrines import (
    DOCTRINE_DIR_DEFAULT,
    load_all_doctrines,
    load_doctrine,
)


def test_catalog_has_starter_set():
    docs = load_all_doctrines()
    assert set(docs).issuperset({"rush", "gunline", "kite", "hold", "reserve"})


def test_rush_doctrine_shape():
    d = load_doctrine("rush")
    assert d.id == "rush"
    assert d.movement.mode == "advance_toward"
    assert d.charge.policy == "always_possible"
    assert d.fall_back.trigger == "never"


def test_gunline_doctrine_shape():
    d = load_doctrine("gunline")
    assert d.movement.mode == "stationary"
    assert d.shooting.target_priority == "highest_threat_value"
    assert d.charge.policy == "never"
    assert d.fall_back.trigger == "never"


def test_kite_doctrine_shape():
    d = load_doctrine("kite")
    assert d.movement.mode == "advance_to_optimal_range"
    assert d.charge.policy == "never"
    assert d.fall_back.trigger == "when_engaged"


def test_hold_doctrine_shape():
    d = load_doctrine("hold")
    assert d.movement.mode == "stationary"
    assert d.charge.policy == "never"
    assert d.fall_back.trigger == "never"


def test_reserve_doctrine_shape():
    d = load_doctrine("reserve")
    assert d.reserve.delay_until_round == 3
    assert d.reserve.sub_doctrine == "rush"


def test_unknown_doctrine_raises():
    with pytest.raises(RuntimeError, match="Unknown doctrine 'ghost'"):
        load_doctrine("ghost")


def test_defaults_applied_when_fields_missing(tmp_path: Path):
    """Partial yaml should inherit defaults for anything it doesn't specify."""
    minimal = tmp_path / "minimal.yaml"
    minimal.write_text(yaml.safe_dump({
        "id": "minimal",
        "movement": {"mode": "stationary"},
    }))
    d = load_doctrine("minimal", doctrine_dir=tmp_path)
    assert d.movement.mode == "stationary"
    # Everything else inherits DEFAULT_DOCTRINE
    assert d.shooting.target_priority == DEFAULT_DOCTRINE.shooting.target_priority
    assert d.charge.policy == DEFAULT_DOCTRINE.charge.policy
    assert d.fall_back.trigger == DEFAULT_DOCTRINE.fall_back.trigger


def test_invalid_mode_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "id": "bad",
        "movement": {"mode": "teleport_through_walls"},
    }))
    with pytest.raises(RuntimeError, match="movement.mode='teleport_through_walls'"):
        load_doctrine("bad", doctrine_dir=tmp_path)


def test_invalid_target_priority_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "id": "bad",
        "shooting": {"target_priority": "random_pick"},
    }))
    with pytest.raises(RuntimeError, match="target_priority='random_pick'"):
        load_doctrine("bad", doctrine_dir=tmp_path)


def test_invalid_charge_policy_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "id": "bad",
        "charge": {"policy": "sprint_and_pray"},
    }))
    with pytest.raises(RuntimeError, match="charge.policy='sprint_and_pray'"):
        load_doctrine("bad", doctrine_dir=tmp_path)


def test_invalid_fall_back_trigger_raises(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "id": "bad",
        "fall_back": {"trigger": "when_vibes_bad"},
    }))
    with pytest.raises(RuntimeError, match="fall_back.trigger='when_vibes_bad'"):
        load_doctrine("bad", doctrine_dir=tmp_path)


def test_unknown_top_level_key_raises():
    with pytest.raises(RuntimeError, match="unknown key 'morale'"):
        DEFAULT_DOCTRINE.merged_with({"morale": {"never_fail": True}})


def test_default_doctrine_is_frozen():
    """Merged_with returns a new Doctrine, never mutates the original."""
    d = DEFAULT_DOCTRINE
    merged = d.merged_with({"movement": {"mode": "stationary"}})
    assert d.movement.mode == "default"
    assert merged.movement.mode == "stationary"
    assert d is not merged
