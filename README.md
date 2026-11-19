# w40k-force-balancer

Warhammer 40,000 combat simulator. Stats-first, dice-math balance analysis. Built to answer the question "given these two armies, what are the actual odds of each winning?" without relying on the point system.

## v1 (current)

Stateless phase-collapse simulator:

- Two YAML force files in, win-odds out.
- Standard 40k combat pipeline per weapon: hit → wound → save → FNP.
- Movement, range, cover, phase separation, and special rules are IGNORED.
- Reports split for A-goes-first vs B-goes-first, plus the 50/50 blend. First-turn swing printed.

```
python3 w40k_sim.py force_a.yaml force_b.yaml --sims 10000
```

See `force_marines.yaml` and `force_orks.yaml` for schema examples.

## v2 (in development)

Full simulator with:

- Real-inch movement on a 44"×30" Combat Patrol board.
- Six-phase turn structure (command, movement, shooting, charge, fight, morale).
- Weapon special rules (Sustained Hits, Lethal Hits, Devastating Wounds, Twin-linked, Torrent, Melta, Rapid Fire, Blast, Hazardous, Anti-KEYWORD).
- Unit abilities (Feel No Pain, Deep Strike, Stealth, Fights First, Deadly Demise, Infiltrators/Scouts).
- Character attachment + Look Out Sir / Precision allocation.
- Stratagems + CP economy.
- Detachment abilities (Shield Host of the Emperor, Mont'ka).
- Markerlights.
- Battleshock.

Statistical approximations applied where simulating true geometry costs more than it earns. Each shortcut carries a `# STAT-APPROX` comment.

## Design principle

Fidelity does not need to be 100% if statistics can model a hard-to-measure outcome. The sim's output is wipe-rate, not table-quarter objective score.

## Catalog-driven rules

Every weapon ability, unit ability, stratagem, and detachment effect lives in `catalog/`. Unknown references in a force YAML fail loud at load time; the sim refuses to simulate a rule it doesn't know.
