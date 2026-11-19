"""Warhammer 40k combat simulator v2 — package scaffold.

Being extracted from the `w40k_sim_v2.py` monolith across a sequence of
behavior-preserving commits:

    1. core (dice + model + board)
    2. load (catalog + force yaml loaders)
    3. rules (weapon / unit abilities, stratagems, detachments)
    4. phases (command / movement / shooting / charge / fight / morale)
    5. engine (game + runner) + CLI entrypoint + public API re-exports

Until the full tree lands, the public re-exports at package root are
deliberately empty — read from the submodules directly. The monolith
`w40k_sim_v2.py` remains authoritative in-tree while the refactor is in
progress; it becomes a thin shim once the engine commit (step 5) lands.
"""
