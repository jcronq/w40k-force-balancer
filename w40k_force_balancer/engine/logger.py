"""Battle logging — structured event stream for a single simulated game.

The engine emits one structured event per decision or activation via the
`BattleLogger` protocol below; consumers choose how to render them.

Four implementations ship:

  * `NullLogger`      — drops everything (engine default).
  * `JsonlLogger`     — one JSON object per line, machine-readable.
  * `MarkdownLogger`  — buffers events and renders a human-readable
                        battle report on `finalize()`.
  * `VerboseStdoutLogger` — mirrors the old `--verbose` decision trace
                            through the same event stream.
  * `MultiLogger`     — fans one event out to multiple loggers.

Event schema (one object per event; `type` discriminates):

  type=deployment         round=0  force units reserves
  type=command            round turn cp strats_declared
  type=movement           round turn actor src_pos dst_pos mode advanced fallback
  type=activation         round turn phase actor target weapon attacks hits
                          wounds unsaved damage models_killed
                          attached_character_damage
  type=charge_attempt     round turn actor target distance roll succeeded
  type=charge_connect     round turn actor target
  type=morale_test        round turn actor roll leadership passed
  type=battleshock_triggered  round turn actor
  type=unit_destroyed     round turn phase actor
  type=strat_used         round turn phase strat_id actor
  type=round_end          round
  type=game_end           round winner reason remaining_wounds_a
                          remaining_wounds_b first_player

The `MarkdownLogger` output deliberately reads like a battle report so a
simulated game can be diffed against a real-game record for calibration.

See README.md "Battle logs" for the replay-against-real-game workflow.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence


Event = dict[str, Any]


class BattleLogger(Protocol):
    """Protocol the engine calls into. All methods are no-op by default."""

    def record(self, event: Event) -> None: ...

    def finalize(self) -> None: ...


class NullLogger:
    """Default sink — drops every event. Used by `simulate_many` so a 5000-
    sim run doesn't pay the per-event overhead."""

    def record(self, event: Event) -> None:
        return

    def finalize(self) -> None:
        return


class JsonlLogger:
    """One JSON object per line, flushed per event.

    Opens the file on construction and truncates any prior contents — logs
    are OVERWRITTEN each run (same as any CLI output file). Call
    `finalize()` to close the handle; the logger also supports use as a
    context manager.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self.path.open("w", encoding="utf-8")

    def record(self, event: Event) -> None:
        self._fp.write(json.dumps(event, sort_keys=True) + "\n")

    def finalize(self) -> None:
        if not self._fp.closed:
            self._fp.flush()
            self._fp.close()

    def __enter__(self) -> "JsonlLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finalize()


class MarkdownLogger:
    """Buffers events and writes a human-readable markdown report on
    `finalize()`.

    The buffer is in-memory; flush cost is paid once per game at game_end.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events: list[Event] = []

    def record(self, event: Event) -> None:
        self._events.append(event)

    def finalize(self) -> None:
        text = _render_markdown(self._events)
        self.path.write_text(text, encoding="utf-8")

    def __enter__(self) -> "MarkdownLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finalize()


class VerboseStdoutLogger:
    """Mirrors the old --verbose decision trace via the shared event stream.

    Keeps stdout output readable: one indented line per interesting event,
    phase headers at the top of each phase block.
    """

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._last_phase_key: tuple[int, str, str] | None = None

    def record(self, event: Event) -> None:
        line = _render_verbose(event)
        if line is None:
            return
        self._stream.write(line + "\n")

    def finalize(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            # Writing to a closed or unfushable stream shouldn't crash the
            # simulation; verbose is cosmetic.
            pass


class MultiLogger:
    """Fan one event stream out to multiple sinks."""

    def __init__(self, loggers: Iterable[BattleLogger]) -> None:
        self._loggers: list[BattleLogger] = list(loggers)

    def record(self, event: Event) -> None:
        for logger in self._loggers:
            logger.record(event)

    def finalize(self) -> None:
        for logger in self._loggers:
            logger.finalize()

    def __enter__(self) -> "MultiLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finalize()


# =============================================================================
# Markdown renderer
# =============================================================================


def _render_markdown(events: Sequence[Event]) -> str:
    """Render the full event stream into a battle report."""
    out: list[str] = []

    # --- Header (derived from deployment + game_end if present) ----------
    deploy_events = [e for e in events if e.get("type") == "deployment"]
    game_end = next((e for e in events if e.get("type") == "game_end"), None)
    header_block = _render_header(deploy_events, game_end)
    out.append(header_block)

    # --- Deployment section ----------------------------------------------
    if deploy_events:
        out.append("## Deployment\n")
        for ev in deploy_events:
            force_label = ev.get("force_name") or f"Force {ev.get('force', '?')}"
            out.append(f"**{force_label}:**")
            for u in ev.get("units") or []:
                attached = u.get("attached_character")
                attach_str = f" (char: {attached})" if attached else ""
                out.append(
                    f"- {u['name']} — {u['models']} model(s), "
                    f"{u['wounds']}W, pos {u['pos']:.1f}\"{attach_str}"
                )
            reserves = ev.get("reserves") or []
            if reserves:
                out.append("- *Reserves:*")
                for u in reserves:
                    out.append(
                        f"  - {u['name']} — {u['models']} model(s), "
                        f"{u['wounds']}W"
                    )
            out.append("")

    # --- Round/turn/phase grouping --------------------------------------
    # Walk the event stream in order, grouping by (round, turn).
    current_round: int | None = None
    current_turn: str | None = None
    current_phase: str | None = None
    for ev in events:
        t = ev.get("type")
        if t in ("deployment", "game_end"):
            continue
        rnd = ev.get("round")
        turn = ev.get("turn")
        phase = ev.get("phase")

        if t == "round_end":
            # round separator
            out.append(f"\n---\n")
            continue

        if rnd is None or turn is None:
            # Non-round-scoped event; skip
            continue

        if rnd != current_round or turn != current_turn:
            out.append(f"\n## Round {rnd} — {turn} Turn\n")
            current_round, current_turn = rnd, turn
            current_phase = None

        if phase and phase != current_phase:
            out.append(f"### {phase.title()} Phase\n")
            current_phase = phase

        line = _render_markdown_event(ev)
        if line:
            out.append(line)

    # --- Final result footer --------------------------------------------
    if game_end is not None:
        out.append("\n## Final Result\n")
        winner = game_end.get("winner", "unknown")
        reason = game_end.get("reason", "")
        wa = game_end.get("remaining_wounds_a", 0)
        wb = game_end.get("remaining_wounds_b", 0)
        first = game_end.get("first_player", "A")
        if winner == "draw":
            out.append(f"**Winner:** draw ({reason})")
        else:
            out.append(f"**Winner:** Force {winner} — {reason}")
        out.append(f"**Remaining wounds:** A={wa}, B={wb}")
        out.append(f"**First player:** {first}")

    return "\n".join(out) + "\n"


def _render_header(deploy_events: Sequence[Event], game_end: Event | None) -> str:
    """Build the top of the markdown file (title + board + seed)."""
    # Force names come from deployment events; fall back to generic labels.
    name_a = "Force A"
    name_b = "Force B"
    for ev in deploy_events:
        force = ev.get("force")
        label = ev.get("force_name")
        if force == "A" and label:
            name_a = label
        elif force == "B" and label:
            name_b = label

    board_w = None
    board_h = None
    gap = None
    seed = None
    first = None
    for ev in deploy_events:
        if board_w is None:
            board_w = ev.get("board_width")
            board_h = ev.get("board_height")
            gap = ev.get("deployment_gap")
        if seed is None:
            seed = ev.get("seed")
        if first is None:
            first = ev.get("first_player")
    if game_end is not None and first is None:
        first = game_end.get("first_player")

    lines = [f"# Battle Report — {name_a} vs {name_b}\n"]
    if board_w is not None:
        lines.append(f"**Board:** {board_w}\"×{board_h}\", deployment gap {gap}\"")
    if seed is not None:
        lines.append(f"**Seed:** {seed}")
    if first is not None:
        lines.append(f"**First turn:** Force {first}")
    lines.append("")
    return "\n".join(lines)


def _render_markdown_event(ev: Event) -> str:
    """Single-event -> one markdown line (or empty string to skip)."""
    t = ev.get("type")
    if t == "command":
        strats = ev.get("strats_declared") or []
        strat_str = f"; strats: {', '.join(strats)}" if strats else ""
        return f"- CP: {ev.get('cp', '?')}{strat_str}"
    if t == "strat_used":
        a = ev.get("actor")
        actor_str = f" ({a})" if a else ""
        return f"- Stratagem: **{ev.get('strat_id')}**{actor_str}"
    if t == "movement":
        actor = ev.get("actor", "?")
        src = ev.get("src_pos")
        dst = ev.get("dst_pos")
        mode = ev.get("mode", "default")
        if src is None or dst is None:
            return f"- {actor} moves [{mode}]"
        delta = dst - src
        extra = []
        if ev.get("advanced"):
            extra.append("advance")
        if ev.get("fallback"):
            extra.append("fall back")
        suffix = f" ({', '.join(extra)})" if extra else ""
        return (
            f"- {actor} moves {delta:+.1f}\" "
            f"[{mode}] -> pos {dst:.1f}\"{suffix}"
        )
    if t == "deep_strike_arrival":
        return f"- {ev.get('actor')} deep-strikes in at pos {ev.get('dst_pos', 0):.1f}\""
    if t == "activation":
        return _render_activation_md(ev)
    if t == "charge_attempt":
        actor = ev.get("actor", "?")
        target = ev.get("target", "?")
        dist = ev.get("distance", 0)
        roll = ev.get("roll", 0)
        if ev.get("succeeded"):
            return (
                f"- {actor} charges {target} "
                f"(distance {dist:.1f}\", rolled {roll}, succeeded)"
            )
        return (
            f"- {actor} fails charge vs {target} "
            f"(distance {dist:.1f}\", rolled {roll})"
        )
    if t == "charge_connect":
        return f"- {ev.get('actor')} already in base contact with {ev.get('target')}"
    if t == "overwatch":
        return (
            f"- Overwatch: {ev.get('actor')} fires at {ev.get('target')} "
            f"(damage {ev.get('damage', 0)})"
        )
    if t == "heroic_intervention":
        return (
            f"- Heroic Intervention: {ev.get('actor')} moves into "
            f"{ev.get('target')}"
        )
    if t == "deep_strike_arrival":
        return f"- {ev.get('actor')} deep-strikes in"
    if t == "fall_back":
        return f"- {ev.get('actor')} falls back"
    if t == "morale_test":
        passed = "passes" if ev.get("passed") else "FAILS"
        return (
            f"- {ev.get('actor')} morale test: rolled {ev.get('roll')} "
            f"vs Ld {ev.get('leadership')} — {passed}"
        )
    if t == "battleshock_triggered":
        return f"- {ev.get('actor')} battleshocked (-1 OC, no strats this round)"
    if t == "unit_destroyed":
        return f"- **{ev.get('actor')} destroyed**"
    return ""


def _render_activation_md(ev: Event) -> str:
    actor = ev.get("actor", "?")
    weapon = ev.get("weapon", "?")
    target = ev.get("target", "?")
    attacks = ev.get("attacks", 0)
    hits = ev.get("hits", 0)
    wounds = ev.get("wounds", 0)
    unsaved = ev.get("unsaved", 0)
    damage = ev.get("damage", 0)
    models_killed = ev.get("models_killed", 0)
    char_dmg = ev.get("attached_character_damage", 0)
    kill_frag = f", {models_killed} model(s) killed" if models_killed else ""
    char_frag = (
        f", {char_dmg} to attached char"
        if char_dmg
        else ""
    )
    return (
        f"- {actor} fires *{weapon}* at {target}: "
        f"{attacks} attacks -> {hits} hits -> {wounds} wounds -> "
        f"{unsaved} unsaved -> {damage} damage{kill_frag}{char_frag}"
    )


# =============================================================================
# Verbose stdout renderer
# =============================================================================


def _render_verbose(ev: Event) -> str | None:
    """Verbose single-line mirror of each event. Returns None to skip."""
    t = ev.get("type")
    rnd = ev.get("round")
    turn = ev.get("turn")
    phase = ev.get("phase")
    prefix = ""
    if t == "deployment":
        force = ev.get("force_name") or f"Force {ev.get('force')}"
        on_board = len(ev.get("units") or [])
        in_res = len(ev.get("reserves") or [])
        return f"[deploy] {force}: {on_board} on board, {in_res} in reserves"
    if t == "game_end":
        return (
            f"[game_end] winner={ev.get('winner')} reason={ev.get('reason')} "
            f"A={ev.get('remaining_wounds_a')} B={ev.get('remaining_wounds_b')}"
        )
    if t == "round_end":
        return f"[round_end] r{rnd}"

    if rnd is not None and turn is not None:
        prefix = f"  r{rnd} {turn} {phase}: "
    body = _render_markdown_event(ev)
    if not body:
        return None
    # Strip leading "- " from the markdown rendering.
    return prefix + body.lstrip("- ")
