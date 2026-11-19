"""Force YAML loader.

Parses a datasheet-style `force_*.yaml` into a `Force` + `Unit` + `Weapon`
tree. Validates every ability / keyword / detachment / faction name against
the catalog; unknown names raise RuntimeError with an actionable message.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..core.model import Catalog, Force, Unit, Weapon


def _parse_weapon(w: dict, cat: Catalog) -> Weapon:
    ab = {}
    for raw in w.get("abilities", []) or []:
        if isinstance(raw, str):
            aid = raw
            overrides = {}
        elif isinstance(raw, dict):
            aid = raw.get("id") or raw.get("name")
            if aid is None:
                raise RuntimeError(f"Weapon ability without id: {raw}")
            overrides = {k: v for k, v in raw.items() if k not in ("id", "name")}
        else:
            raise RuntimeError(f"Weapon ability malformed: {raw!r}")
        entry = cat.require_ability(aid, expected_category="weapon")
        params = dict(entry.params)
        params.update(overrides)
        ab[aid] = params
    return Weapon(
        name=w["name"],
        attacks=int(w["A"]),
        skill=int(w.get("BS", w.get("WS", 4))),
        strength=int(w["S"]),
        ap=int(w.get("AP", 0)),
        damage=int(w["D"]),
        melee=bool(w.get("melee", False)),
        range_in=int(w.get("range", 0 if w.get("melee") else 24)),
        abilities=ab,
    )


def _parse_unit(u: dict, cat: Catalog) -> Unit:
    # Validate keywords
    for kw in u.get("keywords", []) or []:
        cat.require_keyword(kw)
    # Build ability dict
    abilities: dict[str, dict] = {}
    for raw in u.get("abilities", []) or []:
        if isinstance(raw, str):
            aid = raw
            overrides = {}
        elif isinstance(raw, dict):
            aid = raw.get("id") or raw.get("name")
            if aid is None:
                raise RuntimeError(f"Unit ability without id: {raw}")
            overrides = {k: v for k, v in raw.items() if k not in ("id", "name")}
        else:
            raise RuntimeError(f"Unit ability malformed: {raw!r}")
        entry = cat.require_ability(aid)
        if entry.category not in ("unit", "detachment"):
            raise RuntimeError(
                f"Unit ability '{aid}' has category '{entry.category}' — "
                f"only unit/detachment categories are allowed on a unit."
            )
        params = dict(entry.params)
        params.update(overrides)
        abilities[aid] = params
    weapons = [_parse_weapon(w, cat) for w in u.get("weapons", []) or []]

    # Required-fields loud failures
    required = ["name", "models", "T", "W", "Sv"]
    for r in required:
        if r not in u:
            raise RuntimeError(
                f"Unit '{u.get('name', '???')}' missing required field '{r}' "
                f"(need: {required})"
            )
    unit = Unit(
        name=u["name"],
        models=int(u["models"]),
        toughness=int(u["T"]),
        wounds_per_model=int(u["W"]),
        save=int(u["Sv"]),
        inv_save=int(u["InvSv"]) if u.get("InvSv") else None,
        fnp=int(u["FNP"]) if u.get("FNP") else None,
        movement=int(u.get("M", 6)),
        leadership=int(u.get("Ld", 7)),
        oc=int(u.get("OC", 1)),
        keywords=list(u.get("keywords", []) or []),
        abilities=abilities,
        weapons=weapons,
        leader_name=u.get("leader"),
    )
    unit.starting_models = unit.models
    unit._current_model_wounds = unit.wounds_per_model
    return unit


def load_force(path: Path, catalog: Catalog) -> Force:
    """Load a Force from a YAML file. Validates every ability/keyword/detachment
    against the catalog; unknown names raise RuntimeError."""
    data = yaml.safe_load(path.read_text())
    if "name" not in data:
        raise RuntimeError(f"Force yaml {path} missing required 'name'")
    if "units" not in data:
        raise RuntimeError(f"Force yaml {path} missing required 'units'")
    faction = data.get("faction")
    if faction is not None and faction not in catalog.factions:
        raise RuntimeError(
            f"Force '{data['name']}' faction '{faction}' not in catalog "
            f"(see catalog/keywords.yaml factions)."
        )
    det_key = data.get("detachment")
    detachment = None
    if det_key is not None:
        if det_key not in catalog.detachments:
            raise RuntimeError(
                f"Force '{data['name']}' detachment '{det_key}' not found. "
                f"Available: {sorted(catalog.detachments)}"
            )
        detachment = catalog.detachments[det_key]
        if faction and detachment.faction != faction:
            raise RuntimeError(
                f"Detachment '{detachment.name}' is faction '{detachment.faction}' "
                f"but force '{data['name']}' is '{faction}'."
            )
    units = [_parse_unit(u, catalog) for u in data["units"]]

    # Wire character attachments
    by_name = {u.name: u for u in units}
    for u in units:
        if u.leader_name:
            if u.leader_name not in by_name:
                raise RuntimeError(
                    f"Unit '{u.name}' has leader: '{u.leader_name}' but no unit of "
                    f"that name exists in this force."
                )
            squad = by_name[u.leader_name]
            if squad.attached_character is not None:
                raise RuntimeError(
                    f"Squad '{squad.name}' already has an attached character "
                    f"'{squad.attached_character.name}'; can't also attach '{u.name}'."
                )
            squad.attached_character = u
            u.attached_to = squad

    force = Force(
        name=data["name"],
        faction=faction,
        detachment=detachment,
        cp=int(data.get("cp", 4)),
        units=units,
    )
    # Deep-strike reserves setup
    for u in force.units:
        if u.has_ability("DEEP_STRIKE"):
            u.in_reserves = True
    return force
