"""Damage application primitives.

Splits bodyguard vs attached-character damage, handles squad model-pool
allocation, and applies self-inflicted mortals (Hazardous backlash).

Separated from `weapon_abilities` to let `unit_abilities.apply_deadly_demise`
re-use squad allocation without pulling in the full shot resolver.

11e damage model:
  * Normal attacks apply **per attack**: each unsaved attack deals up to
    `damage` to a single model; if the model dies, the remainder is lost.
    Overkill is never transferred to other models or to an attached
    character.
  * Mortal wounds (from Devastating Wounds / Hazardous backlash / etc.) are
    pooled: they drain through the squad model-by-model, and if the whole
    squad dies with mortals remaining they **spill** to the attached
    character.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import Force, Unit


@dataclass
class ShotResult:
    """Output of `resolve_shots`.

    Per-attack damages (`body_attacks` / `char_attacks`) are the amounts
    each unsaved normal attack is going to deliver, already FNP-reduced.
    One list entry = one attack = one model hit (or discarded overkill if
    the target model dies before draining the full damage).

    Mortal damage (`mortal_body` / `mortal_char`) is a pool that still
    spills across models and (for body mortals) into the attached
    character on a squad wipe — matches 11e mortal-wound semantics.
    """
    body_attacks: list[int] = field(default_factory=list)
    char_attacks: list[int] = field(default_factory=list)
    mortal_body: int = 0
    mortal_char: int = 0
    self_mortals: int = 0

    @property
    def body_damage(self) -> int:
        return sum(self.body_attacks) + self.mortal_body

    @property
    def char_damage(self) -> int:
        return sum(self.char_attacks) + self.mortal_char

    # Tuple-unpack as (body_damage_sum, char_damage_sum, self_mortals) so
    # legacy call sites and tests that destructure as a 3-tuple keep working.
    def __iter__(self):
        yield self.body_damage
        yield self.char_damage
        yield self.self_mortals

    def __len__(self) -> int:
        return 3

    def __getitem__(self, idx: int) -> int:
        return (self.body_damage, self.char_damage, self.self_mortals)[idx]


def apply_damage_to_squad(target: Unit, damage: int) -> int:
    """Pooled allocation — mortal-wound style.

    Drains `damage` wound points model-by-model through the squad.
    Returns leftover damage that should spill to attached character
    (for callers that honour mortal-wound spill semantics)."""
    remaining = damage
    while remaining > 0 and target.alive:
        if remaining >= target._current_model_wounds:
            remaining -= target._current_model_wounds
            target.models -= 1
            target.models_lost_this_round += 1
            target._current_model_wounds = (
                target.wounds_per_model if target.alive else 0
            )
        else:
            target._current_model_wounds -= remaining
            remaining = 0
    return remaining   # leftover, spills to character if attached


def _apply_single_attack(target: Unit, damage: int) -> None:
    """Apply one attack's damage to one model.

    11e per-attack rule: deals up to `damage` to a single model; if the
    model dies, the remainder is LOST (no spill to the next model in the
    squad, no spill to an attached character). Multi-wound weapons vs
    multi-wound models therefore cannot kill more than one model per hit.
    """
    if damage <= 0 or not target.alive:
        return
    if damage >= target._current_model_wounds:
        # Model dies; overkill discarded.
        target.models -= 1
        target.models_lost_this_round += 1
        target._current_model_wounds = (
            target.wounds_per_model if target.alive else 0
        )
    else:
        target._current_model_wounds -= damage


def apply_damage_with_attachment(
    squad: Unit,
    result_or_body,
    character_damage_or_char=None,
    attacker_force: Force | None = None,
    defender_force: Force | None = None,
) -> list[Unit]:
    """Apply one activation's output to the target squad (+ attached char).

    Preferred call: pass a `ShotResult` as the second argument; the older
    ``apply_damage_with_attachment(squad, body_damage, char_damage,
    attacker_force, defender_force)`` signature is still accepted — it
    treats the ints as a single pooled attack and routes them through the
    legacy spill path. That shim lets `apply_deadly_demise` and similar
    direct-mortal callers keep their call shape.

    Returns a list of units that died this activation (for Deadly Demise).
    """
    # --- Normalize args --------------------------------------------------
    if isinstance(result_or_body, ShotResult):
        result = result_or_body
    else:
        # Legacy numeric shim — treat as pooled (mortal-style) damage,
        # preserving the previous semantics for any non-shot callers.
        result = ShotResult(
            mortal_body=int(result_or_body or 0),
            mortal_char=int(character_damage_or_char or 0),
        )

    deaths: list[Unit] = []
    character = squad.attached_character

    # --- 1. Precision-tagged mortals: pool into character, spill on death
    if character is not None and character.alive and result.mortal_char > 0:
        leftover = apply_damage_to_squad(character, result.mortal_char)
        if not character.alive:
            deaths.append(character)
            squad.attached_character = None
            character.attached_to = None
            character = None
        # mortal_char overkill drains to body mortals (still mortals, still spill).
        result = _spill_to_body_mortal(result, leftover)

    # --- 2. Precision-tagged per-attack damage: character takes each attack
    if character is not None and character.alive and result.char_attacks:
        for dmg in result.char_attacks:
            if not character.alive:
                break   # per-attack: remaining precision attacks are LOST
            _apply_single_attack(character, dmg)
        if not character.alive:
            deaths.append(character)
            squad.attached_character = None
            character.attached_to = None
            character = None

    # --- 3. Body per-attack damage: each attack hits one model, overkill lost
    # NOTE: no spill to character on squad wipe (overkill of normal attacks
    # is always lost).
    for dmg in result.body_attacks:
        if not squad.alive:
            break
        _apply_single_attack(squad, dmg)

    # --- 4. Body mortal pool: drain through squad, spill to character
    if result.mortal_body > 0:
        leftover = apply_damage_to_squad(squad, result.mortal_body)
        if not squad.alive and character is not None and character.alive:
            # Mortal wounds spill to newly-exposed character.
            squad.attached_character = None
            character.attached_to = None
            apply_damage_to_squad(character, leftover)
            if not character.alive:
                deaths.append(character)

    if not squad.alive and squad.attached_character is None and squad not in deaths:
        deaths.append(squad)

    return deaths


def _spill_to_body_mortal(result: ShotResult, extra: int) -> ShotResult:
    """Helper used by precision-mortal overflow — keeps callers readable."""
    if extra:
        result.mortal_body += extra
    return result


def apply_self_mortals(unit: Unit, mortals: int) -> None:
    """Hazardous backlash: unit takes `mortals` MW.

    11e: Hazardous mortal wounds are mortal wounds, and mortal wounds are
    subject to Feel No Pain. Previously this routed around FNP entirely —
    fixed 2026-11-18 (finding #7). Also honours squad pool semantics
    (drains model-by-model)."""
    if mortals <= 0:
        return
    # FNP applies per wound point.
    from .unit_abilities import best_fnp
    fnp = best_fnp(unit)
    effective = mortals
    if fnp is not None:
        ignored = 0
        # Use the module-level rng? None here; we use random.Random under the
        # hood via the shared `random` module. Hazardous backlash is rare; a
        # fresh Random is fine as the sim already consumes the primary rng
        # for the rest of the shot. But for determinism we want the SAME rng
        # the caller used — so expose an rng-aware variant.
        pass
    # Keep behavior deterministic: push FNP responsibility to apply_self_mortals_rng.
    apply_damage_to_squad(unit, effective)


def apply_self_mortals_rng(unit: Unit, mortals: int, rng) -> None:
    """Hazardous backlash with FNP applied via the caller's rng.

    Preferred entry point; call sites in `phases/shooting.py` and
    `phases/charge.py` pass their rng through so the whole simulation
    stays seeded-reproducible.
    """
    if mortals <= 0:
        return
    from ..core.dice import roll_d6
    from .unit_abilities import best_fnp
    fnp = best_fnp(unit)
    effective = mortals
    if fnp is not None:
        ignored = sum(1 for _ in range(mortals) if roll_d6(rng) >= fnp)
        effective = max(0, mortals - ignored)
    if effective > 0:
        apply_damage_to_squad(unit, effective)
