"""Catalog loader — abilities, keywords, detachments."""
from __future__ import annotations

from pathlib import Path

import yaml

from ..core.model import Catalog, CatalogEntry, Detachment


# Catalog lives at repo_root/catalog; this module is at
# repo_root/w40k_force_balancer/load/catalog.py, so three parents back.
CATALOG_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent / "catalog"


def load_catalog(catalog_dir: Path | None = None) -> Catalog:
    """Load the ability + keyword + detachment catalog from disk."""
    cdir = catalog_dir or CATALOG_DIR_DEFAULT
    if not cdir.exists():
        raise RuntimeError(f"Catalog directory does not exist: {cdir}")

    cat = Catalog()

    # Abilities
    ab_path = cdir / "abilities.yaml"
    if not ab_path.exists():
        raise RuntimeError(f"Missing abilities catalog: {ab_path}")
    ab_data = yaml.safe_load(ab_path.read_text()) or {}
    for aid, spec in ab_data.items():
        cat.abilities[aid] = CatalogEntry(
            id=aid,
            category=spec["category"],
            effect=spec["effect"],
            params=dict(spec.get("params") or {}),
            notes=spec.get("notes", ""),
        )

    # Keywords
    kw_path = cdir / "keywords.yaml"
    if not kw_path.exists():
        raise RuntimeError(f"Missing keywords catalog: {kw_path}")
    kw_data = yaml.safe_load(kw_path.read_text()) or {}
    cat.keywords = set(kw_data.get("universal") or [])
    cat.factions = set(kw_data.get("factions") or [])
    cat.sub_keywords = set(kw_data.get("sub") or [])

    # Detachments
    det_dir = cdir / "detachments"
    if det_dir.exists():
        for det_path in sorted(det_dir.glob("*.yaml")):
            dd = yaml.safe_load(det_path.read_text()) or {}
            name = dd["name"]
            det = Detachment(
                name=name,
                faction=dd["faction"],
                army_ability=dd["army_ability"],
                stratagems=list(dd.get("stratagems") or []),
            )
            # Validate ability refs exist in abilities.yaml
            cat.require_ability(det.army_ability, expected_category="detachment")
            for sid in det.stratagems:
                cat.require_ability(sid, expected_category="stratagem")
            if det.faction not in cat.factions:
                raise RuntimeError(
                    f"Detachment '{name}' faction '{det.faction}' not in catalog/keywords.yaml factions"
                )
            # Keyed by filename (without .yaml) AND by name for convenience
            key = det_path.stem
            cat.detachments[key] = det
    return cat
