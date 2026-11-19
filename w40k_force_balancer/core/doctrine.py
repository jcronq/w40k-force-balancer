"""Doctrine dataclasses + the engine-facing default.

A Doctrine encodes a unit's per-phase decision policy — how aggressive its
movement is, how it picks shooting targets, whether it charges or falls
back. Movement, shooting, charge, and morale/fall-back phases consult the
unit's effective doctrine to decide what to do.

Backward compatibility: a force yaml without `doctrine:` gets `DEFAULT`,
which encodes the pre-doctrine hard-coded engine heuristics:
  * Movement: advance when far, hold when in weapon range (same as the
    old movement.py tactical AI).
  * Shooting: closest-to-dying (lowest total_wounds) within weapon range.
  * Charge: always try when within 12" declaration range.
  * Fall Back: trigger when engaged enemies out-throw this unit's own
    melee attacks (finding #5 heuristic).

Partial overrides at the unit level merge into the force-level doctrine
with Doctrine.merged_with(partial_dict).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


# --- Valid-values registry (raised in load/doctrines.py on unknown refs) ---
VALID_MOVEMENT_MODES = {
    "default",                   # engine heuristic (advance when far, hold in range)
    "advance_toward",            # always move at M (or M+d6 if advance_roll) toward closest enemy
    "advance_away",              # always move at M (or M+d6) away from closest enemy
    "stationary",                # don't move (eligible for HEAVY +1 to hit)
    "advance_to_optimal_range",  # kite — maintain half-range window; back off from engagement
}
VALID_TARGET_PRIORITIES = {
    "closest_threat",            # min pair_distance within weapon range
    "highest_threat_value",      # max attacks * damage * models within weapon range
    "lowest_wounds",             # min total_wounds within weapon range (old engine default)
}
VALID_CHARGE_POLICIES = {
    "always_possible",           # try charge whenever 2d6-reachable (old engine default)
    "never",                     # skip charge phase entirely for this unit
    "conditional",               # charge only if we out-throw the target's melee count back
}
VALID_FALL_BACK_TRIGGERS = {
    "never",                     # stay engaged, fight on
    "when_engaged",              # always Fall Back if engaged this turn
    "only_if_losing",            # Fall Back only when melee-attack math says we're losing
                                 #   (old engine default — finding #5 heuristic)
}


@dataclass(frozen=True)
class DoctrineMovement:
    mode: str = "default"
    advance_roll: bool = False


@dataclass(frozen=True)
class DoctrineShooting:
    target_priority: str = "lowest_wounds"


@dataclass(frozen=True)
class DoctrineCharge:
    policy: str = "always_possible"


@dataclass(frozen=True)
class DoctrineFallBack:
    trigger: str = "only_if_losing"


@dataclass(frozen=True)
class DoctrineReserve:
    # Keep deep-strike units in reserves until this round (minimum arrival).
    # Set to 0 or None to defer to each unit's DEEP_STRIKE ability default.
    delay_until_round: int = 0
    # Sub-doctrine id to apply once reserves land (for `reserve.yaml`).
    sub_doctrine: str | None = None


@dataclass(frozen=True)
class Doctrine:
    id: str = "default"
    description: str = ""
    movement: DoctrineMovement = field(default_factory=DoctrineMovement)
    shooting: DoctrineShooting = field(default_factory=DoctrineShooting)
    charge: DoctrineCharge = field(default_factory=DoctrineCharge)
    fall_back: DoctrineFallBack = field(default_factory=DoctrineFallBack)
    reserve: DoctrineReserve = field(default_factory=DoctrineReserve)
    stratagem_bias: tuple[str, ...] = ()

    def merged_with(self, overrides: dict[str, Any]) -> "Doctrine":
        """Return a new Doctrine with partial overrides applied.

        `overrides` is a nested dict matching the yaml shape — only the
        keys present override the base doctrine. Unknown keys raise
        RuntimeError (keeps typos loud).
        """
        if not overrides:
            return self
        ALLOWED_TOP = {"id", "description", "movement", "shooting", "charge",
                       "fall_back", "reserve", "stratagem_bias"}
        for k in overrides:
            if k not in ALLOWED_TOP:
                raise RuntimeError(
                    f"Doctrine override has unknown key '{k}'. "
                    f"Valid keys: {sorted(ALLOWED_TOP)}"
                )

        new_mov = self.movement
        if "movement" in overrides:
            ov = overrides["movement"] or {}
            if "mode" in ov and ov["mode"] not in VALID_MOVEMENT_MODES:
                raise RuntimeError(
                    f"Doctrine movement.mode='{ov['mode']}' not in "
                    f"{sorted(VALID_MOVEMENT_MODES)}"
                )
            new_mov = replace(
                self.movement,
                mode=ov.get("mode", self.movement.mode),
                advance_roll=bool(ov.get("advance_roll", self.movement.advance_roll)),
            )

        new_shoot = self.shooting
        if "shooting" in overrides:
            ov = overrides["shooting"] or {}
            tp = ov.get("target_priority", self.shooting.target_priority)
            if tp not in VALID_TARGET_PRIORITIES:
                raise RuntimeError(
                    f"Doctrine shooting.target_priority='{tp}' not in "
                    f"{sorted(VALID_TARGET_PRIORITIES)}"
                )
            new_shoot = DoctrineShooting(target_priority=tp)

        new_charge = self.charge
        if "charge" in overrides:
            ov = overrides["charge"] or {}
            policy = ov.get("policy", self.charge.policy)
            if policy not in VALID_CHARGE_POLICIES:
                raise RuntimeError(
                    f"Doctrine charge.policy='{policy}' not in "
                    f"{sorted(VALID_CHARGE_POLICIES)}"
                )
            new_charge = DoctrineCharge(policy=policy)

        new_fb = self.fall_back
        if "fall_back" in overrides:
            ov = overrides["fall_back"] or {}
            trig = ov.get("trigger", self.fall_back.trigger)
            if trig not in VALID_FALL_BACK_TRIGGERS:
                raise RuntimeError(
                    f"Doctrine fall_back.trigger='{trig}' not in "
                    f"{sorted(VALID_FALL_BACK_TRIGGERS)}"
                )
            new_fb = DoctrineFallBack(trigger=trig)

        new_res = self.reserve
        if "reserve" in overrides:
            ov = overrides["reserve"] or {}
            new_res = DoctrineReserve(
                delay_until_round=int(ov.get("delay_until_round",
                                             self.reserve.delay_until_round)),
                sub_doctrine=ov.get("sub_doctrine", self.reserve.sub_doctrine),
            )

        new_bias = self.stratagem_bias
        if "stratagem_bias" in overrides:
            raw = overrides["stratagem_bias"] or []
            if not isinstance(raw, list):
                raise RuntimeError(
                    f"Doctrine stratagem_bias must be a list, got {type(raw).__name__}"
                )
            new_bias = tuple(str(x) for x in raw)

        return Doctrine(
            id=overrides.get("id", self.id),
            description=overrides.get("description", self.description),
            movement=new_mov,
            shooting=new_shoot,
            charge=new_charge,
            fall_back=new_fb,
            reserve=new_res,
            stratagem_bias=new_bias,
        )


# The default doctrine — encodes pre-doctrine engine behavior. Used when a
# force yaml omits `doctrine:` (backward compat).
DEFAULT_DOCTRINE = Doctrine(
    id="default",
    description="Engine heuristic — advance when far, hold when in range; "
                "closest-to-dying target; charge when possible; Fall Back "
                "only when the melee math says we're losing.",
    movement=DoctrineMovement(mode="default", advance_roll=False),
    shooting=DoctrineShooting(target_priority="lowest_wounds"),
    charge=DoctrineCharge(policy="always_possible"),
    fall_back=DoctrineFallBack(trigger="only_if_losing"),
    reserve=DoctrineReserve(),
    stratagem_bias=(),
)
