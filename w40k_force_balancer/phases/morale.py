"""Morale phase — battleshock tests for below-half-strength units."""
from __future__ import annotations

import random

from ..core.dice import roll_2d6
from ..core.model import Force
from ..engine.logger import BattleLogger, NullLogger, VerboseStdoutLogger
from ..rules.stratagems import _can_use_strat, _spend_strat


def morale_phase(
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
    current.used_strats_this_phase = set()
    for u in current.units:
        if not u.alive or u.in_reserves:
            continue
        # 11e: Battleshock test if unit is Below Half Strength at end of turn.
        # For 1-model units, "half strength" is wound points, not model count
        # (finding #4). Previously only triggered when total_wounds<=0, which
        # is already dead — the test could never fire for a solo character.
        start = u.starting_models or u.models
        if start > 1:
            below_half = u.models <= (start // 2)
        else:
            # Single-model unit: below-half when current wounds <= half of
            # starting wounds. Use strict doubling to avoid off-by-one on
            # odd wound counts (e.g. 5W char: triggers at <=2 remaining).
            below_half = u._current_model_wounds * 2 <= u.wounds_per_model
        if below_half:
            # Ld test: 2d6 >= Ld to pass. (We add models_lost_this_round as
            # a crude proxy for 10e's modifier though 11e uses flat 2d6 vs Ld.)
            roll = roll_2d6(rng)
            passed = roll >= u.leadership
            logger.record({
                "round": round_no,
                "turn": turn_side,
                "phase": "morale",
                "type": "morale_test",
                "actor": u.name,
                "roll": roll,
                "leadership": u.leadership,
                "passed": passed,
            })
            if not passed:
                # Failed — battleshock this round.
                if (
                    not current.insane_bravery_used_this_round
                    and _can_use_strat(current, "INSANE_BRAVERY", round_no)
                ):
                    _spend_strat(current, "INSANE_BRAVERY", round_no)
                    current.insane_bravery_used_this_round = True
                    logger.record({
                        "round": round_no,
                        "turn": turn_side,
                        "phase": "morale",
                        "type": "strat_used",
                        "strat_id": "INSANE_BRAVERY",
                        "actor": u.name,
                    })
                else:
                    u.battleshocked_until_round = round_no
                    logger.record({
                        "round": round_no,
                        "turn": turn_side,
                        "phase": "morale",
                        "type": "battleshock_triggered",
                        "actor": u.name,
                    })
        u.models_lost_this_round = 0
