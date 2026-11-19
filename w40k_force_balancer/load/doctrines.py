"""Doctrine catalog loader — reads catalog/doctrines/*.yaml.

Each file describes one named doctrine. Schema:

    id: rush
    description: "..."
    movement:
      mode: advance_toward        # see VALID_MOVEMENT_MODES
      advance_roll: false
    shooting:
      target_priority: closest_threat
    charge:
      policy: always_possible
    fall_back:
      trigger: never
    reserve:
      delay_until_round: 0
      sub_doctrine: null
    stratagem_bias:
      - FIRE_OVERWATCH
      - HEROIC_INTERVENTION

All sub-fields are optional; defaults come from DEFAULT_DOCTRINE. Unknown
mode / target_priority / policy / trigger values raise RuntimeError with
the valid-values list.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..core.doctrine import (
    DEFAULT_DOCTRINE,
    Doctrine,
)


# catalog/doctrines/ lives at repo_root/catalog/doctrines — three parents
# back from this module file.
DOCTRINE_DIR_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent / "catalog" / "doctrines"
)


def _load_doctrine_file(path: Path) -> Doctrine:
    """Parse one doctrine yaml into a Doctrine."""
    raw = yaml.safe_load(path.read_text()) or {}
    doc_id = raw.get("id") or path.stem
    # Start from the engine default, then merge in whatever the yaml declares.
    base = DEFAULT_DOCTRINE
    overrides: dict[str, Any] = dict(raw)
    # `id` is set via the merge so the result inherits the file's id.
    overrides.setdefault("id", doc_id)
    return base.merged_with(overrides)


def load_doctrine(doctrine_id: str, doctrine_dir: Path | None = None) -> Doctrine:
    """Load a single named doctrine by id. Raises RuntimeError if missing."""
    ddir = doctrine_dir or DOCTRINE_DIR_DEFAULT
    path = ddir / f"{doctrine_id}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in ddir.glob("*.yaml")) if ddir.exists() else []
        raise RuntimeError(
            f"Unknown doctrine '{doctrine_id}'. "
            f"Available in {ddir}: {available}"
        )
    return _load_doctrine_file(path)


def load_all_doctrines(doctrine_dir: Path | None = None) -> dict[str, Doctrine]:
    """Load every doctrine in the catalog directory, keyed by id."""
    ddir = doctrine_dir or DOCTRINE_DIR_DEFAULT
    if not ddir.exists():
        return {}
    out: dict[str, Doctrine] = {}
    for p in sorted(ddir.glob("*.yaml")):
        d = _load_doctrine_file(p)
        out[d.id] = d
    return out
