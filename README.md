# w40k-force-balancer

Statistical simulator for Warhammer 40,000 11th edition. Compares army compositions against actual table math rather than the official points system.

Two simulators live side by side:

- `w40k_sim.py` (v1) — stateless phase-collapse simulator. Fast, no movement, no phases, no special rules. Good for pure stat-vs-stat baselines.
- `w40k_force_balancer/` (v2) — real inches, phases, and special rules. Models movement, deployment, shooting ranges, charges, melee, morale, stratagems, detachments. (`w40k_sim_v2.py` at the repo root is a thin backwards-compat shim that calls the package CLI.)

Both kept in-tree so results can be diffed.

## Quick start

```bash
# v2 full head-to-head, 5000 sims x 5 rounds
python3 -m w40k_force_balancer force_custodes_2024cp_v2.yaml force_tau_2024cp_v2.yaml

# Backwards-compat shim — same thing, old invocation
python3 w40k_sim_v2.py force_custodes_2024cp_v2.yaml force_tau_2024cp_v2.yaml

# Verbose single-game trace (phase-by-phase decision log)
python3 -m w40k_force_balancer force_custodes_2024cp_v2.yaml force_tau_2024cp_v2.yaml --verbose

# Side-by-side with v1
python3 w40k_sim.py force_custodes_2024cp.yaml force_tau_2024cp.yaml
python3 -m w40k_force_balancer force_custodes_2024cp_v2.yaml force_tau_2024cp_v2.yaml

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
```

Output: A-wins / B-wins / draw percentages for A-goes-first, B-goes-first, and 50/50 blend. First-turn-advantage swing printed when ≥1 percentage point.

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
  load/
    catalog.py               # abilities.yaml + keywords.yaml + detachments/*.yaml loader
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
    runner.py                # simulate_many + print_report

tests/                       # mirrored structure
  core/{test_dice, test_model, test_board}.py
  load/test_force.py
  rules/{test_weapon_abilities, test_unit_abilities, test_stratagems, test_detachments}.py
  phases/{test_movement, test_shooting, test_charge, test_fight, test_morale}.py
  engine/test_game.py        # full-game + N-sim integration tests
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
```

Unknown ability, keyword, detachment, or faction names fail loud at load time with a `RuntimeError` naming the missing ref. Add to the catalog before referencing in a force YAML.

The v2 force yamls (`force_custodes_2024cp_v2.yaml`, `force_tau_2024cp_v2.yaml`) stay at the repo root alongside the v1 force yamls so both simulators find them with the same relative path.

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
2. Precision character allocation is a flat 50/50 split.
3. Markerlight re-roll effect modelled as -1 to skill target for 2+ markers.
4. ~~Grenade stratagem fires at expected value (6 shots), not sampled 1d6.~~ Fixed 2026-11-18: now samples 1d6 properly each use. Expected value is 3.5, not 6.
5. Overwatch applies the strat universally when it would land.
6. Devastating-wound mortals bypass FNP.

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
