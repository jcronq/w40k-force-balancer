"""Catalog load-time validation tests.

Unknown abilities, unknown keywords, unknown detachments, and malformed
force-yaml references must all raise RuntimeError with an actionable message.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

import w40k_sim_v2 as sim


def _write_yaml(text: str) -> pathlib.Path:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(text)
        return pathlib.Path(f.name)


def test_unknown_weapon_ability_raises(catalog):
    p = _write_yaml("""
name: Bad
units:
  - name: Squad
    models: 1
    T: 4
    W: 1
    Sv: 4
    weapons:
      - {name: Gun, A: 1, BS: 3, S: 4, AP: 0, D: 1,
         abilities: [NOT_A_REAL_ABILITY]}
""")
    try:
        with pytest.raises(RuntimeError, match="Unknown ability"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_unknown_unit_ability_raises(catalog):
    p = _write_yaml("""
name: Bad
units:
  - name: Squad
    models: 1
    T: 4
    W: 1
    Sv: 4
    abilities: [NOT_REAL]
    weapons: []
""")
    try:
        with pytest.raises(RuntimeError, match="Unknown ability"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_unknown_keyword_raises(catalog):
    # Fully uppercase, no underscore → looks universal, must be in catalog.
    p = _write_yaml("""
name: Bad
units:
  - name: Squad
    models: 1
    T: 4
    W: 1
    Sv: 4
    keywords: [FROOBMAN]
    weapons: []
""")
    try:
        with pytest.raises(RuntimeError, match="Unknown keyword"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_unknown_detachment_raises(catalog):
    p = _write_yaml("""
name: Bad
detachment: nonexistent_detachment
units:
  - name: Squad
    models: 1
    T: 4
    W: 1
    Sv: 4
    weapons: []
""")
    try:
        with pytest.raises(RuntimeError, match="detachment 'nonexistent"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_unknown_faction_raises(catalog):
    p = _write_yaml("""
name: Bad
faction: ADEPTUS_FICTIONALIS
units:
  - name: Squad
    models: 1
    T: 4
    W: 1
    Sv: 4
    weapons: []
""")
    try:
        with pytest.raises(RuntimeError, match="faction 'ADEPTUS_FICTIONALIS'"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_missing_required_field_raises(catalog):
    p = _write_yaml("""
name: Bad
units:
  - name: Squad
    models: 1
    # T missing
    W: 1
    Sv: 4
""")
    try:
        with pytest.raises(RuntimeError, match="missing required field 'T'"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_leader_references_nonexistent_unit_raises(catalog):
    p = _write_yaml("""
name: Bad
units:
  - name: Lone Captain
    models: 1
    T: 4
    W: 3
    Sv: 3
    keywords: [INFANTRY, CHARACTER]
    leader: "Nonexistent Squad"
    weapons: []
""")
    try:
        with pytest.raises(RuntimeError, match="no unit of that name"):
            sim.load_force(p, catalog)
    finally:
        os.unlink(p)


def test_full_custodes_load_succeeds(catalog):
    """Sanity: the ships-with-sim force yamls all load clean."""
    base = pathlib.Path(sim.__file__).parent
    force = sim.load_force(base / "force_custodes_2024cp_v2.yaml", catalog)
    assert force.name == "Custodes 2024 CP"
    assert force.detachment is not None
    # Blade Champion attaches to Custodian Guard
    guard = next(u for u in force.units if u.name == "Custodian Guard")
    assert guard.attached_character is not None
    assert guard.attached_character.name == "Blade Champion"


def test_full_tau_load_succeeds(catalog):
    base = pathlib.Path(sim.__file__).parent
    force = sim.load_force(base / "force_tau_2024cp_v2.yaml", catalog)
    assert force.name == "T'au Empire 2024 CP"
    assert force.detachment is not None
    # Pathfinders have markerlight + scouts
    pf = next(u for u in force.units if u.name == "Pathfinders")
    assert "MARKERLIGHT" in pf.abilities
    assert "SCOUTS" in pf.abilities
