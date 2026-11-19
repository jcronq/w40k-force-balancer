"""Force-yaml integration of doctrines — force-level + unit-level overrides."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from w40k_force_balancer.core.doctrine import DEFAULT_DOCTRINE
from w40k_force_balancer.load.force import load_force


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


@pytest.fixture
def minimal_unit():
    return {
        "name": "Testers",
        "models": 3,
        "T": 4,
        "W": 2,
        "Sv": 3,
        "weapons": [{"name": "rifle", "A": 1, "BS": 4, "S": 4, "AP": 0, "D": 1}],
    }


def test_force_without_doctrine_gets_default(tmp_path: Path, catalog, minimal_unit):
    path = _write(tmp_path / "f.yaml", {"name": "F", "units": [minimal_unit]})
    force = load_force(path, catalog)
    assert force.doctrine.id == DEFAULT_DOCTRINE.id
    assert force.units[0].doctrine.id == DEFAULT_DOCTRINE.id


def test_force_doctrine_by_id(tmp_path: Path, catalog, minimal_unit):
    path = _write(tmp_path / "f.yaml", {
        "name": "F", "doctrine": "gunline", "units": [minimal_unit],
    })
    force = load_force(path, catalog)
    assert force.doctrine.id == "gunline"
    assert force.units[0].doctrine.id == "gunline"
    assert force.units[0].doctrine.movement.mode == "stationary"


def test_unit_override_only_affects_that_unit(tmp_path: Path, catalog, minimal_unit):
    u1 = dict(minimal_unit)
    u2 = dict(minimal_unit, name="Movers",
              doctrine={"movement": {"mode": "advance_toward"}})
    path = _write(tmp_path / "f.yaml", {
        "name": "F", "doctrine": "gunline", "units": [u1, u2],
    })
    force = load_force(path, catalog)
    # u1 inherits force gunline
    assert force.units[0].doctrine.movement.mode == "stationary"
    # u2 overrides movement only; rest stays gunline
    assert force.units[1].doctrine.movement.mode == "advance_toward"
    assert force.units[1].doctrine.shooting.target_priority == "highest_threat_value"
    assert force.units[1].doctrine.charge.policy == "never"


def test_unit_doctrine_id_replaces_force_doctrine(tmp_path: Path, catalog, minimal_unit):
    u = dict(minimal_unit, doctrine="rush")
    path = _write(tmp_path / "f.yaml", {
        "name": "F", "doctrine": "gunline", "units": [u],
    })
    force = load_force(path, catalog)
    # Named doctrine at unit level replaces the entire doctrine
    assert force.units[0].doctrine.id == "rush"
    assert force.units[0].doctrine.movement.mode == "advance_toward"
