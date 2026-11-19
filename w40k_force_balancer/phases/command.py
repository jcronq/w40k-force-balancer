"""Command phase: CP gain, detachment declarations, Rapid Ingress."""
from __future__ import annotations

import random

from ..core.model import Force
from ..engine.logger import BattleLogger, NullLogger, VerboseStdoutLogger
from ..rules.detachments import (
    declare_martial_katah_target,
    declare_montka_target,
    maybe_rapid_ingress,
)


def command_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
    logger: BattleLogger | None = None,
    turn_side: str = "A",
) -> None:
    if logger is None:
        logger = VerboseStdoutLogger() if verbose else NullLogger()
    # +1 CP per round (from round 2 on in 11e, but we give from round 1 to keep it simple)
    if round_no >= 2:
        current.cp += 1
    current.used_strats_this_phase = set()
    current.insane_bravery_used_this_round = False

    # Battleshock tests (11e fires at start of command phase technically — the
    # morale phase at round-end is a sim convenience).

    # Detachment declarations
    current.martial_katah_target = None
    current.montka_target = None

    strats_declared: list[str] = []
    if current.detachment is not None:
        det_ab = current.detachment.army_ability
        if det_ab == "MARTIAL_KATAH":
            declare_martial_katah_target(current, enemy, verbose=False)
            if current.martial_katah_target is not None:
                strats_declared.append(
                    f"MARTIAL_KATAH:{current.martial_katah_target.name}"
                )
        elif det_ab == "MONTKA":
            declare_montka_target(current, verbose=False)
            if current.montka_target is not None:
                strats_declared.append(
                    f"MONTKA:{current.montka_target.name}"
                )
        maybe_rapid_ingress(current, round_no, verbose=False)
        if current.rapid_ingress_used:
            # Only append once (flag persists); gate on this_round via strat.
            if ("RAPID_INGRESS", round_no) in current.used_strats_this_round:
                strats_declared.append("RAPID_INGRESS")

    logger.record({
        "round": round_no,
        "turn": turn_side,
        "phase": "command",
        "type": "command",
        "cp": current.cp,
        "strats_declared": strats_declared,
    })
