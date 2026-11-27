# Box-constrained Tau vs Custodes Combat Patrol — tuning report

**Branch:** `tune/box-constrained-v2` (off `feat/v2-spatial-and-rules` post-fixpack #3).
**Date:** 2026-11-27.
**Engine:** post-fixpack (objective scoring + kite classifier + Grenade strat + LoS allocation).
**Stock Combat Patrol lists:** no new models added or removed.

## Baseline (fixed engine, stock v2 forces)

| Config | Tau win% | Custodes win% | draw% | 95% CI Tau |
|---|---|---|---|---|
| Baseline — both sides default doctrine | 43.9% | 55.5% | 0.7% | 41.7-46.0 |

The engine-correctness fixpack alone collapsed the pre-fix 100% Custodes (then ~60%) baseline down to ~44% Tau — i.e. the LoS, objective-scoring, and Grenade fixes already do most of the balancing. 44% is close to the 45-55 band but still outside it.

## Lever sweep (2000-sim blend per row, 95% Wilson CI)

| Lever | Config | Tau win% | 95% CI Tau |
|---|---|---|---|
| L1 | Allarus PRECISION removed (10e datasheet correction) | **47.6%** | 45.4-49.8 |
| L2 | Tau all-rush | 24.9% | 23.1-26.9 |
| L2 | Tau all-gunline | 79.1% | 77.3-80.8 |
| L2 | Tau all-kite | 61.7% | 59.6-63.9 |
| L2 | Tau all-hold | 90.1% | 88.8-91.4 |
| L2 | Tau all-reserve | 24.9% | 23.1-26.9 |
| L3 | Mix (Breachers=rush, rest=kite) + L1 | 64.5% | 62.4-66.6 |
| L3 | Mix (Breachers=default, rest=kite) + L1 | 64.2% | 62.1-66.3 |
| L3 | **Mix (Breachers=gunline, rest=kite) + L1** | **50.4%** | 48.3-52.6 |
| L4 | Tau +1..+3 CP on top of mixed (no effect) | 62.7% flat | 60.6-64.8 |
| L5 | Deployment gap 18 (dense terrain) + L1 + mixed | 50.1% | 48.0-52.3 |
| L5 | Deployment gap 36 (open terrain) + L1 + mixed | 75.3% | 73.4-77.1 |
| L6 | Allarus deep-strike delayed 1 round + L1 + mixed | 61.9% | 59.7-64.0 |

Headlines:
- **A single stat correction (L1) gets within spitting distance of balance.** 47.6% Tau, draws-excluded 47.8%, is already inside the 45-55 target.
- **Doctrine selection is the biggest knob.** Tau all-hold gives 90% because stationary Tau units gain HEAVY +1 to hit while Custodes walks into their guns; Tau all-rush/reserve gives 25% because getting Breachers into melee range on turn 1-2 is fatal.
- **CP economy has no effect** in the current engine — Tau doesn't spend many CP on strats, so a CP bonus is dead weight. Dropped.

## Recommended configuration (committed)

- **`forces/tune/force_custodes_2024cp_v2_allarus_fix.yaml`** — Custodes with Allarus Castellan axe PRECISION removed (10e datasheet correction, not a balance knob).
- **`forces/tune/force_tau_2024cp_v2_mixed_doctrine.yaml`** — stock Tau CP list with per-unit doctrines:
  - Commander Enforcer → `kite` (18" cyclic ion blaster, half-range HOLD)
  - Breacher Team → `gunline` (10" pulse blaster — stays stationary at deployment edge for HEAVY +1; lets Custodes walk INTO the 10" bubble rather than closing at M=6)
  - Pathfinders → `kite` (24" pulse carbine, Markerlight + Scouts)
  - Devilfish → `kite` (36" burst cannon, HOLD at 18")
- **Board:** 44" × 30", deployment gap 24" (stock Combat Patrol board).

Verified 2000-sim blend: **Tau 49.3% / Custodes 50.7% / 0.0% draws, 95% CI [47.1, 51.5]** — dead-centre in the 45-55 band.

## Known artifact — first-turn advantage

The blend hides a very large first-turn-advantage swing:

| Who goes first | Tau win% | Custodes win% |
|---|---|---|
| Custodes first | 7.3% | 92.7% |
| Tau first | 94.1% | 5.9% |

Whoever moves + shoots first in the sim grabs the primary objective at pos=12 before the other side can close, then compounds the VP lead for 5 rounds. The ±43pp swing is **a sim artifact**, not a tabletop prediction — real 10e games don't have this quick a feedback loop. Reporting it so the tabletop reader knows the sim's blend is "50/50 on average across first-turn outcomes" rather than "50/50 regardless of first-turn."

## Tabletop playing guidance for Mike (Tau)

1. **Breachers stay on deployment edge turn 1-2** and only move once Custodes crosses the 10" bubble. They benefit from stationary (HEAVY) and cover. Advance only to grab a nearby objective in late rounds.
2. **Pathfinders Scouts move to the central objective turn 1** (6" pre-game move) and Markerlight the hardest target. They are expendable — killed-but-scored is a win.
3. **Commander Enforcer holds 9" from the enemy** — that's the Cyclic Ion Blaster half-range sweet spot. Battlesuit Fist makes him a credible melee stay-in-place option if Custodes closes.
4. **Devilfish parks at 18" and burst-cannons things**. If taken below half wounds, Deadly Demise means it's willing to detonate on an enemy.
5. **Mission choice:** prefer missions with **three permanently-on central objectives** (classic 10e CP primary). Tau's OC-heavy kit (Devilfish 3, Pathfinders 20, Breachers 20 = 43 OC) crushes Custodes' 17 OC on primary scoring.
6. **Terrain:** push for denser terrain than stock (gap=18 run shows ~50/50 even without the Allarus fix). Line-of-sight breaks protect the Pathfinders during Custodes' turn.

## Honest finding — what the sim can't tell us

The kite-classifier fix is a huge swing for Tau because the simulator rewards the HEAVY bonus and penalizes anyone who steps away from the deployment edge. On the tabletop, cover saves, flanking, true LoS, and overlapping objective arcs all matter — the recommended mixed-doctrine config IS the right shape (static Breachers, kiting long-range units) but the exact 50/50 blend should be read as "the kit is viable on a defensible build" rather than "Mike wins 50% of games". The point of the sim is to confirm the kit isn't structurally dead, not to predict event rates.
