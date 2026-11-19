"""Core data-model sanity — Unit/Force copy semantics + wound bookkeeping."""
from __future__ import annotations

import w40k_force_balancer as sim
from tests.conftest import make_weapon, make_unit


def test_unit_copy_preserves_state_but_resets_engagement():
    u = make_unit(name="Squad", models=5, wounds_per_model=2)
    u.engaged_with.add(42)
    u._current_model_wounds = 1
    clone = u.copy()
    assert clone.name == "Squad"
    assert clone.models == 5
    assert clone.wounds_per_model == 2
    # Copy resets per-game runtime state: engagements emptied, model-wound reset.
    assert clone.engaged_with == set()
    assert clone._current_model_wounds == 2
    # And it's a deep-enough copy — mutating the clone doesn't bleed back.
    clone.models = 1
    assert u.models == 5


def test_unit_total_wounds_counts_partial_model():
    u = make_unit(name="Squad", models=3, wounds_per_model=4)
    u._current_model_wounds = 2
    # 2 whole models @ 4W + 1 partial @ 2W = 10.
    assert u.total_wounds == 10


def test_force_copy_rewires_character_attachment():
    captain = make_unit(name="Captain", models=1, keywords=["INFANTRY", "CHARACTER"])
    captain.leader_name = "Squad"
    squad = make_unit(name="Squad", models=5)
    squad.attached_character = captain
    captain.attached_to = squad
    f = sim.Force(name="F", units=[squad, captain])
    clone = f.copy()
    cloned_squad = next(u for u in clone.units if u.name == "Squad")
    cloned_cap = next(u for u in clone.units if u.name == "Captain")
    assert cloned_squad.attached_character is cloned_cap
    assert cloned_cap.attached_to is cloned_squad
