"""Historical usage backfill and cross-game usage comparison (Stack 3).

Turns preserved evidence for games that predate live usage collection --
Fireworks `requests/*/request.json`+`response.json`+receipts (including old
failed responses) and explicitly bound Codex host sessions (Stack 2's
`tools.collect_model_usage`) -- into the same `model_calls` rows a live
adapter would have written, then merges them into an already-catalogued
game without ever inventing a new game from a relocated archive copy.

Hard rules, matched to the frozen contract in tmp/plan_token_usage.md:

- A game is resolved ONLY by its already-catalogued `games.artifact_path`
  identity. This module never imports a new game; run `game_history import`
  first. A relocated copy of the same evidence must never become a second
  game (its identity is the manifest's declared `game_id`, unchanged).
- A backfill manifest is required and explicit: it maps exactly the game IDs
  it names to exactly the evidence describing how to recover their usage.
  `--all` selects only games the manifest maps -- never every catalog game.
- Backfill is additive, never destructive: newly discovered calls are merged
  with whatever `model_calls` rows the game already has (via
  `tools.model_usage.dedupe_calls`'s UPSERT-by-identity semantics, run
  through the same `tools.game_history.import_usage_sidecar` entry point
  Stack 1/2 already use) rather than replacing them outright. A source that
  cannot be read at all leaves previously imported usage completely
  untouched. Two preserved copies of the same evidence collapse to the same
  call identity and are never double-counted as two paid retries.
- Every selected game is independent: one missing/malformed source fails
  only that game and never touches another game's rows or its own prior
  rows.
- Defaults to dry-run/inventory. Only `--execute` writes anything.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import game_history as gh
from . import collect_model_usage as host_usage
from .model_usage import ModelCall, TOKEN_FIELDS, aggregate_calls, dedupe_calls, normalize_usage, source_identity

MANIFEST_KINDS = ("fireworks_requests", "host_session")


class UsageBackfillError(RuntimeError):
    """A game's evidence could not be backfilled at all (this game fails)."""


class UsageBackfillUnavailable(UsageBackfillError):
    """The named source path itself does not exist -- distinct from malformed content."""


class BackfillManifestError(ValueError):
    """The manifest file itself is missing, unreadable, or structurally invalid."""


def load_backfill_manifest(path: str | Path) -> dict[str, dict[str, Any]]:
    """Load `{"games": {game_id: {"kind": ..., ...}}}` from an explicit JSON manifest.

    Never globs or scans a directory for games to include -- only the games
    named here are ever eligible for backfill, including for `--all`.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise BackfillManifestError(f"cannot read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BackfillManifestError(f"manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, Mapping) or not isinstance(raw.get("games"), Mapping):
        raise BackfillManifestError(f"manifest {path} must be an object with a 'games' object")
    games: dict[str, dict[str, Any]] = {}
    for game_id, entry in raw["games"].items():
        if not isinstance(entry, Mapping) or entry.get("kind") not in MANIFEST_KINDS:
            raise BackfillManifestError(
                f"manifest entry for {game_id!r} must be an object with kind in {MANIFEST_KINDS}")
        games[str(game_id)] = dict(entry)
    return {"games": games}


# --- Fireworks preserved-archive evidence -----------------------------------
#
# Real preserved shape (verified against actual archives; only key paths and
# types were inspected -- no prompt/response content is embedded in fixtures
# here): a `requests/` directory holding one subdirectory per attempt, named
# `<dispatch-time-ns>-<prompt-sha256-prefix>` -- itself a stable, source-
# derived attempt identity allocated before dispatch. Each attempt directory
# holds `request.json` (the outgoing chat-completions body), `response.json`
# (the complete provider reply, including nested `usage`) when a reply was
# received at all, `receipt.json` (a flat summary including `prompt_sha256`,
# `elapsed_seconds`, and a duplicate of `usage`), and either `reply.json`
# (the client accepted an answer) or `error.json` (the client rejected an
# empty/invalid answer, e.g. `finish_reason=length`). An attempt directory
# with no `response.json` at all never reached the provider -- it is a
# locally blocked attempt and owns zero calls, exactly like the live adapter.
#
# Fireworks nests cache-read and reasoning counts one level deeper than
# `tools.model_usage.FIREWORKS_USAGE_MAP` expects (`prompt_tokens_details.
# cached_tokens`, `completion_tokens_details.reasoning_tokens`). This module
# flattens those two paths into synthetic top-level keys before calling the
# SAME `tools.model_usage.normalize_usage` Stack 1 owns, using a locally
# extended field map -- `tools/model_usage.py` itself is never edited. The
# raw, unflattened object is retained verbatim in `raw_usage_json`.

_FIREWORKS_ARCHIVE_USAGE_MAP = {
    "prompt_tokens": "input_tokens",
    "completion_tokens": "output_tokens",
    "total_tokens": "total_tokens",
    "cached_tokens_flat": "cached_input_tokens",
    "reasoning_tokens_flat": "reasoning_tokens",
}


def _flatten_fireworks_usage(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    flat = dict(raw)
    cached = raw.get("prompt_tokens_details")
    if isinstance(cached, dict) and isinstance(cached.get("cached_tokens"), (int, float)):
        flat["cached_tokens_flat"] = cached["cached_tokens"]
    reasoning = raw.get("completion_tokens_details")
    if isinstance(reasoning, dict) and "reasoning_tokens" in reasoning:
        flat["reasoning_tokens_flat"] = reasoning["reasoning_tokens"]
    return flat


def _read_json_optional(path: Path) -> tuple[Any, str | None]:
    """Read one JSON file. Returns (value, diagnostic). A missing file is not
    itself a diagnostic -- callers decide whether absence is meaningful
    (e.g. no `reply.json` on a rejected attempt is normal)."""
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name}:{exc}"


def parse_fireworks_attempt(game_id: str, attempt_dir: Path) -> tuple[ModelCall | None, list[str]]:
    """Parse one preserved attempt directory into a ModelCall, or None.

    None means the attempt never reached the provider (no `response.json`):
    a locally blocked attempt owns zero calls, per the frozen contract.
    """
    diagnostics: list[str] = []

    def read(name: str) -> Any:
        value, diag = _read_json_optional(attempt_dir / name)
        if diag is not None:
            diagnostics.append(f"{attempt_dir.name}:{diag}")
        return value

    request_data = read("request.json") or {}
    response_data = read("response.json")
    receipt_data = read("receipt.json") or {}
    reply_data = read("reply.json")
    error_data = read("error.json")

    if not isinstance(response_data, dict):
        return None, diagnostics

    provider_response_id = response_data.get("id")
    call_id = source_identity("fireworks", None, provider_response_id, attempt_dir.name)

    choices = response_data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    finish_reason = (choice.get("finish_reason") if isinstance(choice, dict) else None) \
        or (receipt_data.get("finish_reason") if isinstance(receipt_data, dict) else None)

    if reply_data is not None and isinstance(content, str) and content.strip():
        status = "completed"
    elif error_data is not None:
        status = "failed"
    else:
        status = "unknown"

    raw_usage = response_data.get("usage")
    normalized, gaps = normalize_usage(_flatten_fireworks_usage(raw_usage), _FIREWORKS_ARCHIVE_USAGE_MAP)

    elapsed_seconds = receipt_data.get("elapsed_seconds") if isinstance(receipt_data, dict) else None
    elapsed_ms = (int(elapsed_seconds * 1000)
                  if isinstance(elapsed_seconds, (int, float)) and not isinstance(elapsed_seconds, bool) else None)

    call = ModelCall(
        game_id=game_id, call_id=call_id, provider="fireworks",
        transport="fireworks_chat_completions_archive",
        provider_response_id=provider_response_id if isinstance(provider_response_id, str) else None,
        requested_model=request_data.get("model") if isinstance(request_data.get("model"), str) else None,
        reported_model=response_data.get("model") if isinstance(response_data.get("model"), str)
        else receipt_data.get("runtime_model"),
        output_limit=request_data.get("max_completion_tokens")
        if isinstance(request_data.get("max_completion_tokens"), int) else None,
        status=status,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        error_code=(error_data.get("message") or error_data.get("type"))
        if isinstance(error_data, dict) else None,
        elapsed_ms=elapsed_ms,
        usage_source="preserved_provider_response" if raw_usage is not None else None,
        raw_usage_json=raw_usage,
        source_ref=str(attempt_dir),
        source_hash=receipt_data.get("prompt_sha256") if isinstance(receipt_data, dict) else None,
        linkage_evidence=None,
        normalization_gaps=gaps,
    )
    for field, value in normalized.items():
        setattr(call, field, value)
    return call, diagnostics


def collect_fireworks_calls(game_id: str, requests_dir: str | Path) -> tuple[list[ModelCall], list[str]]:
    """Parse every attempt directory under `requests_dir` into ModelCall rows.

    Attempt directories are visited in name order (their name is prefixed by
    dispatch-time nanoseconds, so this is also chronological) for stable,
    idempotent output across reruns. Two preserved copies of the same
    evidence (same response id / same attempt directory name) yield the same
    `call_id` and are folded together by the caller's `dedupe_calls`, never
    counted as two paid retries.
    """
    root = Path(requests_dir)
    if not root.is_dir():
        raise UsageBackfillUnavailable(f"requests_dir does not exist or is not a directory: {root}")
    calls: list[ModelCall] = []
    diagnostics: list[str] = []
    for attempt_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        call, attempt_diagnostics = parse_fireworks_attempt(game_id, attempt_dir)
        diagnostics.extend(attempt_diagnostics)
        if call is not None:
            calls.append(call)
    return calls, diagnostics


def collect_host_session_calls(game_id: str, entry: Mapping[str, Any]) -> tuple[list[ModelCall], list[str]]:
    """Collect calls for an explicitly bound Codex host session (Stack 2 reuse).

    Every path comes from the manifest entry -- never resolved by scanning a
    session index or a home directory. See `tools.collect_model_usage` for
    the read-only thread-ID verification this delegates to.
    """
    required = ("host_thread_id", "host_evidence_path", "game_log_path", "request_handshake_dir")
    missing = [key for key in required if not entry.get(key)]
    if missing:
        raise UsageBackfillError(f"host_session manifest entry missing field(s): {', '.join(missing)}")
    manifest_dict = {"game_id": game_id, **{key: entry[key] for key in required}}
    try:
        manifest = host_usage.load_manifest(manifest_dict)
    except host_usage.ManifestError as exc:
        raise UsageBackfillUnavailable(str(exc)) from exc
    report = host_usage.collect_host_usage_report(manifest)
    calls = [ModelCall(**row) for row in report["calls"]]
    diagnostics = [f"{d.get('kind')}:{d.get('source_path')}:{d.get('position')}" for d in report["diagnostics"]]
    if not report["thread_finalized"]:
        diagnostics.append("host_thread_not_finalized")
    return calls, diagnostics


def link_calls_by_unique_prompt_hash(conn, game_id: str,
                                     calls: list[ModelCall]) -> int:
    """Link backfilled calls to harness requests by UNIQUE prompt hash.

    A preserved receipt records the sha256 of the exact prompt that was sent,
    and the match log records the same hash on the harness request that sent
    it. Where a hash identifies exactly ONE request in this game, that is
    unique evidence of which request paid for the call - the kind Stack 3
    requires - not the nth-call pairing or timestamp proximity it forbids.

    A hash shared by more than one request proves nothing about which of them a
    call belongs to, so those calls stay unlinked. This is linkage only: prompt
    hashes must never merge calls, because two paid retries of one prompt are
    two calls, and both were paid for.
    """
    counts: dict[str, list[str]] = {}
    for request_id, prompt_hash in conn.execute(
            "SELECT request_id, prompt_hash FROM model_requests "
            "WHERE game_id=? AND prompt_hash IS NOT NULL", (game_id,)):
        counts.setdefault(prompt_hash, []).append(request_id)
    unique = {h: ids[0] for h, ids in counts.items() if len(ids) == 1}
    linked = 0
    for call in calls:
        if call.request_id or not call.source_hash:
            continue
        request_id = unique.get(call.source_hash)
        if request_id:
            call.request_id = request_id
            call.linkage_evidence = "prompt_sha256_unique"
            linked += 1
    return linked


def _collect_entry_calls(game_id: str, entry: Mapping[str, Any]) -> tuple[list[ModelCall], list[str]]:
    kind = entry.get("kind")
    if kind == "fireworks_requests":
        requests_dir = entry.get("requests_dir")
        if not requests_dir:
            raise UsageBackfillError("fireworks_requests manifest entry requires 'requests_dir'")
        return collect_fireworks_calls(game_id, requests_dir)
    if kind == "host_session":
        return collect_host_session_calls(game_id, entry)
    raise UsageBackfillError(f"unsupported manifest kind: {kind!r}")


def backfill_one_game(conn, game_id: str, entry: Mapping[str, Any], execute: bool = False) -> dict[str, Any]:
    """Backfill one already-catalogued game's usage, in its own transaction.

    Additive: merges newly discovered calls with the game's existing
    `model_calls` rows (queried through the maintained `query_usage` API,
    never a fresh table scan) via the same UPSERT-by-identity semantics
    Stack 1/2 use, applied through `tools.game_history.import_usage_sidecar`
    so this module never duplicates that table-write logic. Nothing is
    written unless `execute=True`; a dry run reports exactly what an execute
    run would do.
    """
    if conn.execute("SELECT 1 FROM games WHERE game_id=?", (game_id,)).fetchone() is None:
        return {"game_id": game_id, "status": "unavailable", "reason": "unknown_game_id"}

    try:
        new_calls, diagnostics = _collect_entry_calls(game_id, entry)
        # Prove harness links from unique prompt-hash evidence before storing.
        linked = link_calls_by_unique_prompt_hash(conn, game_id, new_calls)
    except UsageBackfillUnavailable as exc:
        return {"game_id": game_id, "status": "unavailable", "reason": str(exc)}
    except UsageBackfillError as exc:
        return {"game_id": game_id, "status": "failed", "reason": str(exc)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"game_id": game_id, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}

    if not new_calls and diagnostics:
        # The source was reachable but nothing recoverable came out of it --
        # e.g. every attempt directory had an unreadable/corrupt JSON file.
        # This is a malformed-source failure, not an empty-but-clean archive
        # (that case reaches here with diagnostics == [] and is reported as
        # `imported` with zero new calls, same as backfill-events' honest
        # "no evidence" outcome).
        return {"game_id": game_id, "status": "failed",
                "reason": f"malformed source: {sorted(set(diagnostics))}",
                "diagnostics": sorted(set(diagnostics))}

    existing_rows = gh.query_usage(conn, game_id, "call")["calls"]
    existing_calls = [ModelCall(**row) for row in existing_rows]
    merged, conflicts = dedupe_calls(existing_calls + new_calls)
    result: dict[str, Any] = {
        "game_id": game_id,
        "status": "imported",
        "new_calls_found": len(dedupe_calls(new_calls)[0]),
        "calls_before": len(existing_calls),
        "calls_after": len(merged),
        # How much of the recovered spending could be tied to a harness request
        # by unique evidence. The rest stays unlinked rather than guessed.
        "linked_by_prompt_hash": linked,
        "diagnostics": sorted(set(diagnostics)),
        "conflicts": {f"{g}:{c}": v for (g, c), v in conflicts.items()},
        "measured": aggregate_calls(merged),
        "dry_run": not execute,
    }
    if not execute:
        return result

    with conn:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sidecar_path = Path(tmp_dir) / "backfill_usage.ndjson"
            with sidecar_path.open("w", encoding="utf-8") as stream:
                for call in merged:
                    stream.write(json.dumps(dict(call.to_row(), record_kind="final"),
                                             sort_keys=True, default=str) + "\n")
            gh._apply_usage_calls(conn, game_id, sidecar_path)
    return result


def backfill_usage(conn, game_ids: Iterable[str] = (), manifest_path: str | Path | None = None,
                    all_games: bool = False, execute: bool = False) -> dict[str, Any]:
    """Backfill selected games' usage from an explicit manifest.

    `all_games=True` selects exactly the games the manifest maps -- never
    every catalog game. A selected game absent from the manifest is reported
    `unavailable` rather than raising, so one caller typo cannot abort a
    batch that also names good games.
    """
    if manifest_path is None:
        raise ValueError("backfill-usage requires --manifest")
    manifest = load_backfill_manifest(manifest_path)
    games_map = manifest["games"]
    ids = list(games_map.keys()) if all_games else list(dict.fromkeys(game_ids))
    if not all_games and not ids:
        raise ValueError("backfill-usage requires --game-id (one or more) or --all")

    report: dict[str, Any] = {"attempted": len(ids), "execute": execute,
                              "imported": [], "unavailable": [], "failed": []}
    for game_id in ids:
        entry = games_map.get(game_id)
        if entry is None:
            report["unavailable"].append({"game_id": game_id, "reason": "not_in_manifest"})
            continue
        outcome = backfill_one_game(conn, game_id, entry, execute=execute)
        report[outcome["status"]].append(outcome)
    return report


# --- Cross-game usage comparison ---------------------------------------------

def _percentile_over_groups(groups: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """Median/max of `field` over groups whose detail has that field fully
    measured -- an open or partially-measured group is excluded, not zeroed,
    and the excluded count travels with the result so a reader can see how
    much of the comparison the percentile actually covers."""
    included: list[int] = []
    for group in groups:
        info = group["detail"][field]
        if info["fully_measured"] and info["sum"] is not None:
            included.append(info["sum"])
    return {"median": statistics.median(included) if included else None,
            "max": max(included) if included else None,
            "included_count": len(included), "excluded_count": len(groups) - len(included)}


def _distinct(values: Iterable[Any]) -> list[Any]:
    return sorted({v for v in values if v is not None}, key=str)


def compare_usage(conn, game_ids: Iterable[str]) -> dict[str, Any]:
    """Compare measured usage across explicitly selected games at matching granularity.

    No ranking or "fair comparison" score is computed -- callers get the same
    measured/aggregate/coverage figures `usage` already reports, plus
    request- and completed-side-turn-level output/reasoning percentiles
    (fully-measured groups only) and open/failed-turn usage kept visibly
    separate from completed-turn figures. Raw token counts are measurements
    of different tokenizers, not a ranking of model strength.
    """
    ids = list(dict.fromkeys(game_ids))
    if not ids:
        raise ValueError("compare-usage requires explicit --game-id selection")

    games: list[dict[str, Any]] = []
    for game_id in ids:
        if conn.execute("SELECT 1 FROM games WHERE game_id=?", (game_id,)).fetchone() is None:
            games.append({"game_id": game_id, "status": "unknown_game_id"})
            continue
        game_row = conn.execute(
            """SELECT source_commit, dirty_patch_hash, parent_game_id, lineage_root_id
               FROM games WHERE game_id=?""", (game_id,)).fetchone()
        players = [dict(zip(("side", "backend", "model_requested", "model_reported",
                             "reasoning_requested", "reasoning_reported"), row))
                   for row in conn.execute(
                       """SELECT side,backend,model_requested,model_reported,
                          reasoning_requested,reasoning_reported FROM game_players
                          WHERE game_id=? ORDER BY side""", (game_id,))]
        game_report = gh.query_usage(conn, game_id, "game")
        request_report = gh.query_usage(conn, game_id, "request")
        turn_report = gh.query_usage(conn, game_id, "turn")
        call_report = gh.query_usage(conn, game_id, "call")
        calls = call_report["calls"]
        failed_calls = [c for c in calls if c["status"] == "failed"]
        completed_calls = [c for c in calls if c["status"] == "completed"]

        request_groups = [{"id": r["request_id"], "detail": r["detail"]}
                          for r in request_report["requests"] if r["detail"] is not None]
        completed_turn_groups = [{"id": t["side_turn_id"], "detail": t["detail"]}
                                 for t in turn_report["completed_turns"]]

        distinct_prompt_hashes = conn.execute(
            "SELECT COUNT(DISTINCT prompt_hash) FROM model_requests WHERE game_id=? AND prompt_hash IS NOT NULL",
            (game_id,)).fetchone()[0]

        games.append({
            "game_id": game_id,
            "status": "ok",
            "source_commit": game_row[0], "dirty_patch_hash": game_row[1],
            "parent_game_id": game_row[2], "lineage_root_id": game_row[3],
            "continuity": "resumed" if game_row[2] else "root",
            "players": players,
            "requested_models": _distinct(c["requested_model"] for c in calls),
            "reported_models": _distinct(c["reported_model"] for c in calls),
            "requested_reasoning_efforts": _distinct(c["requested_reasoning_effort"] for c in calls),
            "reported_reasoning_efforts": _distinct(c["reported_reasoning_effort"] for c in calls),
            "output_limits": _distinct(c["output_limit"] for c in calls),
            "transports": _distinct(c["transport"] for c in calls),
            "system_instruction_note": ("system-instruction identity is not separately tracked; "
                                        "distinct_prompt_hashes is a proxy only, never proof of "
                                        "identical or differing system instructions"),
            "distinct_prompt_hashes": distinct_prompt_hashes,
            "game_level": {"measured": game_report["measured"], "call_count": game_report["call_count"],
                          "aggregate_only_request_ids": game_report["aggregate_only_request_ids"],
                          "unassigned": turn_report["unassigned"],
                          "attribution_coverage": turn_report["attribution_coverage"]},
            "per_request": {"count": len(request_groups),
                           "output_tokens": _percentile_over_groups(request_groups, "output_tokens"),
                           "reasoning_tokens": _percentile_over_groups(request_groups, "reasoning_tokens")},
            "per_completed_side_turn": {
                "count": len(completed_turn_groups),
                "output_tokens": _percentile_over_groups(completed_turn_groups, "output_tokens"),
                "reasoning_tokens": _percentile_over_groups(completed_turn_groups, "reasoning_tokens")},
            "open_turns": turn_report["open_turns"],
            "failed_calls": {"count": len(failed_calls),
                             "detail": aggregate_calls(ModelCall(**c) for c in failed_calls)},
            "completed_calls": {"count": len(completed_calls),
                                "detail": aggregate_calls(ModelCall(**c) for c in completed_calls)},
        })

    return {
        "games": games,
        "note": ("cross-model tokenizers differ; raw token counts are measurements, not equal "
                 "units of compute, and no strength ranking follows from a lower count alone. "
                 "Old request-only aggregates and new call detail are never summed into one total."),
    }


def _format_compare_report(value: dict[str, Any]) -> str:
    lines: list[str] = []
    for game in value["games"]:
        if game["status"] != "ok":
            lines.append(f"{game['game_id']}: {game['status']}")
            continue
        measured = game["game_level"]["measured"]
        lines.append(f"{game['game_id']}: calls={game['game_level']['call_count']} "
                    f"output_sum={measured['output_tokens']['sum']} "
                    f"reasoning_sum={measured['reasoning_tokens']['sum']} "
                    f"input_sum={measured['input_tokens']['sum']} "
                    f"linked_fraction={game['game_level']['attribution_coverage']['linked_fraction']}")
        lines.append(f"  requested_models={game['requested_models']} "
                    f"transports={game['transports']}")
        lines.append(f"  per_request output p50/max={game['per_request']['output_tokens']['median']}/"
                    f"{game['per_request']['output_tokens']['max']} "
                    f"(included={game['per_request']['output_tokens']['included_count']}, "
                    f"excluded={game['per_request']['output_tokens']['excluded_count']})")
        lines.append(f"  open_turns={len(game['open_turns'])} failed_calls={game['failed_calls']['count']}")
    lines.append(value["note"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI, exercised via game_history
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill-usage")
    backfill.add_argument("--db", required=True)
    backfill.add_argument("--manifest", required=True)
    selector = backfill.add_mutually_exclusive_group(required=True)
    selector.add_argument("--game-id", action="append")
    selector.add_argument("--all", action="store_true")
    backfill.add_argument("--execute", action="store_true")
    compare = sub.add_parser("compare-usage")
    compare.add_argument("--db", required=True)
    compare.add_argument("--game-id", action="append", required=True)
    compare.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    conn = gh.open_history(args.db, read_only=(args.command == "compare-usage"))
    exit_code = 0
    if args.command == "backfill-usage":
        value = backfill_usage(conn, args.game_id or [], args.manifest, args.all, args.execute)
        if value["unavailable"] or value["failed"]:
            exit_code = 1
        print(json.dumps(value, sort_keys=True, default=str))
    else:
        value = compare_usage(conn, args.game_id)
        print(json.dumps(value, sort_keys=True, default=str) if args.json else _format_compare_report(value))
    conn.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
