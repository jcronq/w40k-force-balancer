"""Command phase: CP gain, detachment declarations, Rapid Ingress."""
from __future__ import annotations

import random

from ..core.model import Force
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
) -> None:
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
    if current.detachment is None:
        return
    det_ab = current.detachment.army_ability
    if det_ab == "MARTIAL_KATAH":
        declare_martial_katah_target(current, enemy, verbose)
    elif det_ab == "MONTKA":
        declare_montka_target(current, verbose)

    maybe_rapid_ingress(current, round_no, verbose)
