"""Morale phase — battleshock tests for below-half-strength units."""
from __future__ import annotations

import random

from ..core.dice import roll_2d6
from ..core.model import Force
from ..rules.stratagems import _can_use_strat, _spend_strat


def morale_phase(
    current: Force,
    enemy: Force,
    round_no: int,
    rng: random.Random,
    verbose: bool = False,
) -> None:
    current.used_strats_this_phase = set()
    for u in current.units:
        if not u.alive or u.in_reserves:
            continue
        # 11e: Battleshock test if unit is Below Half Strength at end of turn.
        start = u.starting_models or u.models
        below_half = u.models <= (start // 2) if start > 1 else u.total_wounds <= 0
        if below_half:
            # Ld test: 2d6 >= Ld to pass. (We add models_lost_this_round as
            # a crude proxy for 10e's modifier though 11e uses flat 2d6 vs Ld.)
            roll = roll_2d6(rng)
            if roll < u.leadership:
                # Failed — battleshock this round.
                if (
                    not current.insane_bravery_used_this_round
                    and _can_use_strat(current, "INSANE_BRAVERY", round_no)
                ):
                    _spend_strat(current, "INSANE_BRAVERY", round_no)
                    current.insane_bravery_used_this_round = True
                    if verbose:
                        print(f"    [{current.name}] INSANE_BRAVERY saves {u.name}")
                else:
                    u.battleshocked_until_round = round_no
                    if verbose:
                        print(f"    [{current.name}] {u.name} FAILS battleshock (-1 OC, no strats)")
        u.models_lost_this_round = 0
