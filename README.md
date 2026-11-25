# w40k-force-balancer

Statistical simulator for Warhammer 40,000 11th edition. Compares army compositions against actual table math rather than the official points system.

Two simulators live side by side:

- `w40k_sim.py` (v1) — stateless phase-collapse simulator. Fast, no movement, no phases, no special rules. Good for pure stat-vs-stat baselines.
- `w40k_force_balancer/` (v2) — real inches, phases, and special rules. Models movement, deployment, shooting ranges, charges, melee, morale, stratagems, detachments. (`w40k_sim_v2.py` at the repo root is a thin backwards-compat shim that calls the package CLI.)

Both kept in-tree so results can be diffed.

## Quick start

```bash
# v2 full head-to-head, 5000 sims x 5 rounds
python3 -m w40k_force_balancer forces/force_custodes_2024cp_v2.yaml forces/force_tau_2024cp_v2.yaml

# Backwards-compat shim — same thing, old invocation
python3 w40k_sim_v2.py forces/force_custodes_2024cp_v2.yaml forces/force_tau_2024cp_v2.yaml

# Verbose single-game trace (phase-by-phase decision log)
python3 -m w40k_force_balancer forces/force_custodes_2024cp_v2.yaml forces/force_tau_2024cp_v2.yaml --verbose

# Side-by-side with v1
python3 w40k_sim.py forces/force_custodes_2024cp.yaml forces/force_tau_2024cp.yaml
python3 -m w40k_force_balancer forces/force_custodes_2024cp_v2.yaml forces/force_tau_2024cp_v2.yaml

# Custom board
python3 -m w40k_force_balancer A.yaml B.yaml --board-width 60 --board-height 44 --deployment-gap 36

# Tests
python3 -m pytest tests/
```

## CLI

```
python3 -m w40k_force_balancer force_a.yaml force_b.yaml
    [--sims N]              # default 5000
    [--rounds N]            # default 5
    [--seed S]              # default 0
    [--board-width W]       # default 44 in
    [--board-height H]      # default 30 in
    [--deployment-gap G]    # default 24 in (Combat Patrol)
    [--catalog-dir PATH]    # default ./catalog
    [--verbose]             # single-game decision trace
    [--doctrine-a ID]       # override A's doctrine (rush/gunline/kite/hold/reserve)
    [--doctrine-b ID]       # override B's doctrine
    [--matrix]              # run every doctrine permutation, print the grid
    [--matrix-sims N]       # sims per matrix cell (default 2000)
    [--log-game FILE.md]    # single-game markdown battle report (see Battle logs)
    [--log-game-jsonl FILE.jsonl]
                            # single-game JSONL event stream (see Battle logs)
```

Output: A-wins / B-wins / draw percentages for A-goes-first, B-goes-first, and 50/50 blend. First-turn-advantage swing printed when ≥1 percentage point.

## Doctrines

A **doctrine** is a per-phase tactical policy — how the unit moves, who it shoots, whether it charges, when it Falls Back. Instead of hard-coding one tactical AI in the engine, each unit consults its effective doctrine every phase. That lets the simulator answer questions like *"what happens if T'au just hold their ground vs. what if they kite vs. what if they charge?"* by swapping doctrines, not code.

Each doctrine lives as one yaml in `catalog/doctrines/`. Starter set shipped:

| Doctrine | Movement | Shooting | Charge | Fall Back | Flavour |
|---|---|---|---|---|---|
| `rush` | `advance_toward` (+d6 when far) | closest threat | always | never | Custodes default |
| `gunline` | `stationary` (HEAVY +1) | highest threat value | never | never | T'au static |
| `kite` | `advance_to_optimal_range` | closest threat | never | when engaged | Mobile T'au |
| `hold` | `stationary` | closest threat | never | never | Fight-from-cover stand-in |
| `reserve` | advance_toward + deep-strike delay | closest threat | always | never | Ambush |

Schema per doctrine yaml:

```yaml
id: rush
description: "Advance every round, charge when possible, never retreat."
movement:
  mode: advance_toward            # advance_toward | advance_away | stationary | advance_to_optimal_range | default
  advance_roll: true              # if true, +d6 Advance (only gates in when out of 12" charge range)
shooting:
  target_priority: closest_threat # closest_threat | highest_threat_value | lowest_wounds
charge:
  policy: always_possible         # always_possible | never | conditional
fall_back:
  trigger: never                  # never | when_engaged | only_if_losing
reserve:
  delay_until_round: 0            # hold DEEP_STRIKE units in reserves until this round
  sub_doctrine: null              # id applied to non-reserve units
stratagem_bias:
  - HEROIC_INTERVENTION
  - COMMAND_REROLL
```

### Overriding at force or unit level

Force yaml: add `doctrine: <id>` at the top level.

```yaml
name: "T'au Empire 2024 CP"
faction: TAU_EMPIRE
detachment: montka
doctrine: gunline            # whole force plays static
units: ...
```

Unit yaml: add `doctrine:` to a single unit. A string replaces the entire doctrine; a dict is a partial override merged onto the force doctrine.

```yaml
units:
  - name: "Pathfinders"
    doctrine: kite           # named override — full replace
    ...
  - name: "Breacher Team"
    doctrine:                # partial override — still inherits force gunline shoot/charge/fall-back
      movement:
        mode: advance_toward
```

Omit `doctrine:` entirely and the engine falls back to the `default` doctrine (the pre-doctrine hard-coded tactical AI — advance when far, closest-to-dying target, charge when in range, Fall Back only when losing the melee math). Backward compat preserved for every force yaml that pre-dates this feature.

## Matrix mode

Run every `(doctrine_a, doctrine_b)` permutation against each other:

```bash
python3 -m w40k_force_balancer forces/force_custodes_2024cp_v2.yaml forces/force_tau_2024cp_v2.yaml --matrix
```

Each cell prints `A-wins% / B-wins% / draws%` on the 50/50 first-turn blend. The summary at the end calls out:

- Total cells each force wins.
- Each side's best doctrine (highest average win rate across the opposing doctrines).
- For each opposing doctrine, the matchup that lands best for that side.

Example (2000 sims/cell):

```
DOCTRINE MATRIX — Custodes 2024 CP vs T'au Empire 2024 CP, 2,000 sims per cell
  Board: 44"x30" (gap 24")
  Cells: A-wins / B-wins / draws (50/50 blend, %)

  cols: T'au Empire 2024 CP doctrine
  rows: Custodes 2024 CP doctrine

                   rush            gunline         kite            hold            reserve
  --------------------------------------------------------------------------------------------
  rows: rush       98.4/ 1.6/0.0   29.6/67.9/2.5   32.9/64.8/2.3   24.8/72.3/2.9   99.0/ 1.0/0.0
  rows: gunline    99.8/ 0.2/0.0   35.6/57.6/6.8    7.9/88.0/4.1   47.0/41.3/11.7  99.9/ 0.1/0.0
  rows: kite       79.7/19.6/0.7   30.2/63.7/6.1   65.8/27.1/7.1   39.0/52.4/8.6   79.2/19.9/0.9
  rows: hold       97.9/ 2.0/0.1    3.2/95.8/1.0   25.9/67.6/6.5    4.4/94.1/1.5   97.5/ 1.9/0.6
  rows: reserve    98.8/ 1.1/0.1   30.6/67.1/2.3   33.5/63.8/2.7   25.1/72.2/2.7   99.1/ 0.9/0.0

  Custodes 2024 CP wins 12/25 matchups; T'au Empire 2024 CP wins 13/25.
  Custodes 2024 CP's best doctrine is kite (58.3% avg win rate).
  T'au Empire 2024 CP's best doctrine is gunline (69.0% avg win rate).
```

Read the matrix as: each row is a Custodes doctrine, each column a T'au doctrine, and the cell is the win rate if both sides lock into those tactics the whole game. Live numbers vary by RNG seed; use `--matrix-sims` + `--seed` to tighten or compare.

## Battle logs

The aggregate N-sim run prints percentages; the matrix prints a grid. Neither tells you what happened *inside* a single game. Two flags emit a per-game log so a simulated game can be compared with — or diffed against — a real tabletop record:

```bash
# Markdown — human-readable battle report
python3 -m w40k_force_balancer force_a.yaml force_b.yaml --log-game game.md --seed 0

# JSONL — machine-readable event stream (one JSON object per line)
python3 -m w40k_force_balancer force_a.yaml force_b.yaml --log-game-jsonl game.jsonl --seed 0

# Both at once — same game, two sinks
python3 -m w40k_force_balancer force_a.yaml force_b.yaml \
    --log-game game.md --log-game-jsonl game.jsonl --seed 0
```

Either flag forces single-game mode (ignores `--sims`) and respects `--seed` — same seed, same game. Both files are overwritten per run. `--verbose` still works on its own; combining it with the log flags fans the shared event stream to all three sinks.

### Markdown format

Reads like a battle report:

```markdown
# Battle Report — Custodes 2024 CP vs T'au Empire 2024 CP

**Board:** 44"×30", deployment gap 24"
**Seed:** 0
**First turn:** Force A

## Deployment

**Custodes 2024 CP:**
- Blade Champion — 1 model(s), 6W, pos 0.0"
- Custodian Guard — 5 model(s), 15W, pos 0.0" (char: Blade Champion)
- *Reserves:*
  - Allarus Custodians — 3 model(s), 12W

**T'au Empire 2024 CP:**
- Commander in Enforcer Battlesuit — 1 model(s), 7W, pos 0.0"
- Fire Warriors Breacher Team — 10 model(s), 10W, pos 0.0"
- Pathfinders — 10 model(s), 10W, pos 6.0"
- Devilfish — 1 model(s), 11W, pos 0.0"

## Round 1 — A Turn

### Command Phase
- CP: 3; strats: MARTIAL_KATAH:Pathfinders, RAPID_INGRESS

### Movement Phase
- Blade Champion moves +10.0" [default] -> pos 10.0" (advance)
- Custodian Guard moves +10.0" [default] -> pos 10.0" (advance)

### Shooting Phase
- Allarus Custodians fires *Balistus grenade launcher (ranged)* at Commander in Enforcer Battlesuit: 3 attacks -> 2 hits -> 0 wounds -> 0 unsaved -> 0 damage

## Round 1 — B Turn
...

## Final Result

**Winner:** Force A — B wiped
**Remaining wounds:** A=18, B=0
**First player:** A
```

### JSONL event schema

One JSON object per line. `type` discriminates the event. Full event-type list:

| type | fields |
|------|--------|
| `deployment` | `force` `force_name` `units[]` `reserves[]` `board_width` `board_height` `deployment_gap` `first_player` `seed` |
| `command` | `round` `turn` `cp` `strats_declared[]` |
| `movement` | `round` `turn` `actor` `src_pos` `dst_pos` `mode` `advanced` `fallback` |
| `deep_strike_arrival` | `round` `turn` `actor` `dst_pos` |
| `activation` | `round` `turn` `phase` `actor` `target` `weapon` `attacks` `hits` `wounds` `unsaved` `damage` `models_killed` `attached_character_damage` |
| `charge_attempt` | `round` `turn` `actor` `target` `distance` `roll` `succeeded` |
| `charge_connect` | `round` `turn` `actor` `target` |
| `heroic_intervention` | `round` `turn` `actor` `target` |
| `morale_test` | `round` `turn` `actor` `roll` `leadership` `passed` |
| `battleshock_triggered` | `round` `turn` `actor` |
| `strat_used` | `round` `turn` `phase` `strat_id` `actor` |
| `unit_destroyed` | `round` `turn` `phase` `actor` |
| `round_end` | `round` |
| `game_end` | `round` `winner` `reason` `remaining_wounds_a` `remaining_wounds_b` `first_player` |

Sample line (shooting activation):

```json
{"round": 1, "turn": "A", "phase": "shooting", "type": "activation",
 "actor": "Custodian Guard", "target": "Breacher Team",
 "weapon": "Guardian spear (ranged)", "attacks": 10, "hits": 8,
 "wounds": 6, "unsaved": 4, "damage": 8, "models_killed": 4,
 "attached_character_damage": 0}
```

### Replay-against-real-game calibration workflow

The sim is a model. Models drift. The battle-log outputs exist so a *simulated* game can be laid alongside a *played* game and the places where they diverge become the calibration punch-list.

Rough loop:

1. Play a real game against a specific opponent list. Record the force yamls on both sides (keep them exactly what hit the table).
2. Re-run the sim on those yamls with `--log-game game.md --seed <some seed> --rounds <rounds played>`. Try several seeds; pick the one whose first-round shape (first-player movement choices, first charge attempt, first unit wiped) best matches what happened at the table.
3. Diff the markdown report against your notes from the real game. Where the sim consistently over- or under-predicts — e.g. "sim's Breacher Team always eats a Guardian spear activation in round 1, but at the table they stayed out of range because of terrain" — you've found a model fidelity gap.
4. Fix: either a yaml mismatch (wrong profile, missing ability), a doctrine miscalibration (the sim's rush-doctrine closes faster than a human does), or an engine simplification (1D distance collapses terrain). The `type=activation` events let you zero in on which weapon / target / phase is off: `jq 'select(.type=="activation" and .actor=="Breacher Team")' game.jsonl`.
5. Re-sim and iterate.

The JSONL is the authoritative diff target — it's stable across runs with the same seed, and `jq`-friendly. The markdown is for human eyeballing.

## Code layout

The v2 simulator was extracted from `w40k_sim_v2.py` into the `w40k_force_balancer` package in Nov 2026. Behavior-preserving refactor; CLI output is byte-identical to the monolith.

```
w40k_force_balancer/
  __init__.py                # package root, re-exports public API
  __main__.py                # `python -m w40k_force_balancer` entrypoint
  cli.py                     # argparse glue
  core/
    dice.py                  # d6, 2d6, to-wound chart
    model.py                 # Weapon / Unit / Force / Catalog dataclasses + phase constants
    board.py                 # Board + 1D-distance model + module `_BOARD`
    doctrine.py              # Doctrine + per-phase policy dataclasses + DEFAULT_DOCTRINE
  load/
    catalog.py               # abilities.yaml + keywords.yaml + detachments/*.yaml loader
    doctrines.py             # doctrines/*.yaml loader
    force.py                 # force_*.yaml loader + catalog validation
  rules/
    damage.py                # squad allocation, bodyguard spillover, self-mortals
    unit_abilities.py        # FNP, Deadly Demise
    weapon_abilities.py      # resolve_shots (the shot resolver, Sustained/Lethal/Dev/...)
    stratagems.py            # CP gate + spend helpers
    detachments.py           # Martial Ka'tah + Mont'ka declarations, Rapid Ingress
  phases/
    command.py               # CP gain, detachment declarations, Rapid Ingress
    movement.py              # deep-strike arrivals + advance / move AI
    shooting.py              # ranged activations, Grenade strat, Markerlight, Mont'ka
    charge.py                # 2d6 charges + Overwatch + Heroic Intervention
    fight.py                 # tiers + alternating activations
    morale.py                # below-half battleshock + Insane Bravery
  engine/
    game.py                  # setup_initial_positions + simulate_game (one match)
    runner.py                # simulate_many + print_report + simulate_matrix

forces/                      # ships-with-sim force YAMLs (v1 + v2, Custodes/Tau/Marines/Orks)

tests/                       # mirrored structure
  core/{test_dice, test_model, test_board}.py
  load/{test_force, test_doctrines, test_force_doctrines}.py
  rules/{test_weapon_abilities, test_unit_abilities, test_stratagems, test_detachments}.py
  phases/{test_movement, test_shooting, test_charge, test_fight, test_morale}.py
  phases/{test_movement_doctrines, test_shooting_doctrines, test_charge_doctrines}.py
  engine/{test_game, test_matrix}.py
```

Public API (`import w40k_force_balancer as sim`): `load_catalogs` / `load_force` / `run_simulation` / `main`, plus every dataclass + phase function + rule helper for direct use.

## Catalog structure

Data lives at the repo root in the `catalog/` directory — kept out of the package so it can be edited without touching Python code.

```
catalog/
  abilities.yaml        # every weapon/unit/stratagem/detachment ability
  keywords.yaml         # valid keywords (universal / faction / sub)
  detachments/
    shield_host.yaml    # Custodes — Shield Host of the Emperor
    montka.yaml         # T'au — Mont'ka
  doctrines/
    rush.yaml           # advance + charge
    gunline.yaml        # stationary + highest-threat targeting
    kite.yaml           # optimal-range + Fall Back on engage
    hold.yaml           # stationary + closest-threat
    reserve.yaml        # delay deep-strike to r3
```

Unknown ability, keyword, detachment, or faction names fail loud at load time with a `RuntimeError` naming the missing ref. Add to the catalog before referencing in a force YAML.

Force YAMLs live under `forces/` — v1 and v2 side-by-side (`forces/force_custodes_2024cp.yaml`, `forces/force_custodes_2024cp_v2.yaml`, `forces/force_tau_2024cp.yaml`, `forces/force_tau_2024cp_v2.yaml`, plus `forces/force_marines.yaml` / `forces/force_orks.yaml`). Both the v1 and v2 simulators resolve paths relative to the invocation cwd, so pass `forces/force_*.yaml` on the CLI.

## Force YAML schema

```yaml
name: "Custodes 2024 CP"             # required
faction: ADEPTUS_CUSTODES            # optional; must be in keywords.yaml factions
detachment: shield_host              # optional; must match a file under detachments/
cp: 4                                # starting CP; default 4

units:
  - name: "Blade Champion"
    models: 1
    M: 6         # movement
    T: 6         # toughness
    W: 6         # wounds per model
    Sv: 2        # armor save
    InvSv: 4     # optional invulnerable save
    FNP: null    # optional native Feel No Pain
    Ld: 6        # leadership
    OC: 1        # objective control (not used in sim yet)
    keywords: [INFANTRY, CHARACTER, ADEPTUS_CUSTODES]
    abilities:
      - FIGHTS_FIRST                 # bare id uses catalog defaults
      - {id: SUSTAINED_HITS, n: 1}   # dict form overrides params
      - LEADER
    leader: "Custodian Guard"        # attach this unit as char to that squad
    weapons:
      - name: "Vaultswords"
        A: 6       # attacks
        WS: 2      # weapon skill (or BS for ranged)
        S: 7       # strength
        AP: 3      # positive AP value (AP3)
        D: 2       # damage
        melee: true
        range: 0   # 0 for melee
        abilities:
          - PRECISION
          - {id: SUSTAINED_HITS, n: 1}
```

### Required fields per unit

`name`, `models`, `T`, `W`, `Sv`. Everything else has a default. Missing required fields raise `RuntimeError`.

## Modelled rules (v2 scope)

### Weapon abilities

All implemented (see `catalog/abilities.yaml` for parameters):

| Ability | Effect |
|---|---|
| `SUSTAINED_HITS` | each crit-hit adds N auto-hits |
| `LETHAL_HITS` | 6-to-hit auto-wounds, skip to-wound |
| `DEVASTATING_WOUNDS` | 6-to-wound → D mortals, bypass saves+FNP |
| `TWIN_LINKED` | re-roll failed wound rolls |
| `TORRENT` | auto-hit, no hit roll |
| `MELTA` | +N damage within half-range |
| `RAPID_FIRE` | +N shots per model within half-range |
| `BLAST` | +1 attack per 5 full models in target unit |
| `HAZARDOUS` | 1-to-hit → bearer takes 1 MW |
| `ANTI_X` | wound-rolls of N+ crit vs X-keyword target |
| `PISTOL` | fires in melee |
| `HEAVY` | +1 to hit if bearer remained stationary |
| `PRECISION` | 50% of damage lands on attached character |

### Unit abilities

| Ability | Effect |
|---|---|
| `FEEL_NO_PAIN` | each wound ignored on d6 ≥ N |
| `DEEP_STRIKE` | starts in reserves, arrives round 2 at 9" from enemy edge |
| `STEALTH` | incoming ranged hit rolls get -1 |
| `FIGHTS_FIRST` / `FIGHTS_LAST` | priority tier in fight phase |
| `DEADLY_DEMISE` | d6 on death, N MW to closest enemy on threshold+ |
| `INFILTRATORS` | start 9" closer to enemy |
| `SCOUTS` | pre-game move of N inches |
| `FOR_THE_GREATER_GOOD` | Fire Overwatch on 5+ instead of 6+ |
| `MARKERLIGHT` | place marker tokens on 4+ (cap 3) |

### Stratagems (CP economy)

Each force starts with 4 CP. +1 CP per round from round 2 onward. Available stratagems depend on the chosen detachment:

| Strat | CP | Phase | Effect |
|---|---|---|---|
| `FIRE_OVERWATCH` | 1 | Charge | Defender fires at 6+ (5+ with FGG) when charged |
| `RAPID_INGRESS` | 1 | Command | One deep-striker arrives round 1 |
| `HEROIC_INTERVENTION` | 1 | Charge | Free 3" move into melee with charger |
| `INSANE_BRAVERY` | 1 | Morale | Auto-pass one battleshock test |
| `COMMAND_REROLL` | 1 | Any | Re-roll one die (sim fires on failed charge) |
| `GRENADE` | 1 | Shooting | 1d6 S6 AP-1 D1 attacks at infantry within 8" |

### Detachment abilities

- **Shield Host of the Emperor** (Custodes): `MARTIAL_KATAH` — at the start of each command phase, nominate one enemy unit; all Custodes units get +1 to wound rolls in melee against that unit this round.
- **Mont'ka** (T'au): at the start of each command phase, nominate one T'au unit; that unit fires twice in the shooting phase this round.

### Phase loop

Per round, each force in turn-order:

```
Command → Movement → Shooting → Charge → Fight → Morale
```

In the Fight phase, all `FIGHTS_FIRST` units activate first (both sides, active-player priority); then normal units; then `FIGHTS_LAST`.

## Statistical approximation licenses

Fidelity does not need to be 100% when statistics can model a hard-to-measure outcome. Every shortcut is tagged `STAT-APPROX:` in the source — audit with `grep -r STAT-APPROX w40k_force_balancer/`.

Active approximations:

1. 1D distance collapse (no left-right drift, no LoS graph).
2. ~~Precision character allocation is a flat 50/50 split.~~ Fixed 2026-11-18 (finding #6): per-hit Bernoulli(0.5) instead of ceil(n/2).
3. ~~Markerlight re-roll effect modelled as -1 to skill target for 2+ markers.~~ Fixed 2026-11-18 (finding #3): real re-roll in the hit loop (all failed for 2+ markers, raw 1s for 1 marker).
4. ~~Grenade stratagem fires at expected value (6 shots), not sampled 1d6.~~ Fixed 2026-11-18: now samples 1d6 properly each use. Expected value is 3.5, not 6.
5. Overwatch applies the strat universally when it would land.
6. Devastating-wound mortals bypass FNP.
7. Fall Back heuristic (finding #5): compares total melee attack counts, not expected damage.

## Known ambiguities

Judgment calls made where Wahapedia was unclear or 11th-ed phrasing was contested. Open to override — PR a change or file an issue:

- **FNP vs Devastating-wound mortals** — current: FNP does NOT apply to dev-wound mortals (11e core rules). Some players argue native unit FNP should still apply; toggle via the `mortal_damage_points` branch in `resolve_shots()`.
- **Sustained Hits + Torrent** — current: Torrent skips the hit roll, so no crits generated, so Sustained Hits is inert when paired. 11e rules are silent on this interaction.
- **Rapid Ingress timing** — current: can be used in round 1 command phase. 11e rules say "end of any opponent's turn." Simplified for sim.
- **Anti-KEYWORD + modifier cap** — current: anti threshold is checked against the raw wound roll, not the modified one. 11e tournament ruling tends toward modified roll; swap in `resolve_shots` if desired.
- **Mont'ka target selection** — current: picks the T'au unit with the highest `attacks × models` ranged weapon total. 11e actually requires the unit to be in range of at least one enemy; sim picks regardless.
- **Overwatch targeting** — current: defender overwatches the charger. 11e lets the defender overwatch *any* enemy within range. Simplified.
- **Multi-target shooting** — current: each weapon on a unit picks its own closest-to-dying target in range. 11e lets the unit split fire per model; close to equivalent in expectation.

## Data sources

11th edition datasheets, accessed 2026-11-18, via Wahapedia:

- Blade Champion: https://wahapedia.ru/wh40k11ed/factions/adeptus-custodes/blade-champion
- Allarus Custodians: https://wahapedia.ru/wh40k11ed/factions/adeptus-custodes/allarus-custodians
- Custodian Guard: https://wahapedia.ru/wh40k11ed/factions/adeptus-custodes/custodian-guard
- Shield Host detachment: https://wahapedia.ru/wh40k11ed/factions/adeptus-custodes/
- Commander (Enforcer): https://wahapedia.ru/wh40k11ed/factions/tau-empire/commander-in-enforcer-battlesuit
- Breacher Team: https://wahapedia.ru/wh40k11ed/factions/tau-empire/breacher-team
- Pathfinders: https://wahapedia.ru/wh40k11ed/factions/tau-empire/pathfinders
- Devilfish: https://wahapedia.ru/wh40k11ed/factions/tau-empire/devilfish
- Mont'ka detachment: https://wahapedia.ru/wh40k11ed/factions/tau-empire/

## Tests

Mirror the package structure one-for-one:

```
tests/
  core/
    test_dice.py               # to_wound chart + clamp
    test_model.py               # Unit / Force copy semantics, wound bookkeeping
    test_board.py               # pair_distance, closest_enemy{,_within}
  load/
    test_force.py               # catalog validation + full force-yaml load
  rules/
    test_weapon_abilities.py    # one case per weapon ability
    test_unit_abilities.py      # FNP, Deep Strike, Stealth, FF, DD, Infil, Scouts, FGG, Markerlight
    test_stratagems.py          # CP economy + every implemented strat
    test_detachments.py         # Martial Ka'tah, Mont'ka
  phases/
    test_movement.py            # advance / normal move / gap-clamp
    test_charge.py              # 2d6 charge, fail, declaration-range cap
    test_shooting.py            # engagement locks out non-pistol shooting
    test_fight.py               # engaged units trade damage
    test_morale.py              # below-half battleshock
  engine/
    test_game.py                # full-game smoke + 500-sim pinned blend
    test_logger.py              # BattleLogger protocol + renderers
    test_game_logging.py        # end-to-end logger-captured game
    test_matrix.py              # doctrine matrix sweep
  test_cli.py                   # --log-game / --log-game-jsonl CLI paths
```

Run from the repo root:

```bash
python3 -m pytest tests/ -q
```

Every ability in `catalog/abilities.yaml` has at least one test case showing the expected behaviour on a known-state battlefield; unknown-ref failures are covered in `tests/load/test_force.py`.

## Design notes

- **State lives in Unit/Force**; the sim is otherwise stateless — rerun with a fresh `rng` for independent games. `simulate_game` copies the input forces, so original yamls stay pristine.
- **No dependencies beyond PyYAML + stdlib.** Python 3.10+.
- **No silent defaults** — missing required fields fail at load time.
- **No illegal moves** — units can't move more than M, charge > 12", fire out of range, fight if not engaged, or spend a stratagem their detachment doesn't have.

Comparison with v1:

| Dimension | v1 | v2 |
|---|---|---|
| Spatial | ignored | 1D distance per pair |
| Phases | 1 (fire both) | 6 (command/move/shoot/charge/fight/morale) |
| Weapon rules | none | 13 rules |
| Unit rules | FNP / inv only | 9 rules + FNP native |
| Stratagems | none | 6 + CP economy |
| Detachment | none | 2 (Shield Host, Mont'ka) |
| Characters | none | leader attach + Look Out Sir + Precision |
| Reserves | none | Deep Strike + Rapid Ingress |
| Morale | none | battleshock 2d6 vs Ld |
