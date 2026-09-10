"""Offline prompt-prefix measurements and measured cache summaries.

This reports byte eligibility separately from provider token measurements.  It
never treats equal text or a missing provider field as a cache hit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .model_usage import ModelCall, TOKEN_FIELDS, aggregate_calls


def common_prefix_bytes(a: bytes, b: bytes) -> int:
    limit = min(len(a), len(b))
    index = 0
    while index < limit and a[index] == b[index]:
        index += 1
    return index


def report_prompts(prompts: Iterable[str | bytes | None]) -> dict[str, Any]:
    values = [value if isinstance(value, bytes) else value.encode("utf-8") if isinstance(value, str) else None
              for value in prompts]
    if not values:
        return {"request_count": 0, "prompt_available": 0, "compared_pairs": 0,
                "coverage": None, "comparison_scope": "canonical_prompt_bytes", "requests": []}
    rows = [{"prompt_bytes": len(value) if value is not None else None,
             "prompt_sha256": hashlib.sha256(value).hexdigest() if value is not None else None}
            for value in values]
    pairs = [common_prefix_bytes(values[i - 1], values[i]) for i in range(1, len(values))
             if values[i - 1] is not None and values[i] is not None]
    return {"request_count": len(values), "compared_pairs": len(pairs),
            "prompt_available": sum(value is not None for value in values),
            "shared_prefix_bytes": pairs,
            "coverage": {"available_requests": sum(value is not None for value in values),
                         "total_requests": len(values),
                         "available_adjacent_pairs": len(pairs),
                         "total_adjacent_pairs": max(0, len(values) - 1)},
            "comparison_scope": "canonical_prompt_bytes", "requests": rows}


def report_archive(path: str | Path) -> dict[str, Any]:
    prompts: list[bytes] = []
    rows: list[dict[str, Any]] = []
    archive = Path(path)
    source = archive / "match.ndjson" if archive.is_dir() else archive
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") != "model_request":
            continue
        prompt = record.get("prompt")
        prompts.append(prompt if isinstance(prompt, str) else None)
        rows.append({key: record.get(key) for key in
                     ("request_id", "sequence", "prompt_layout_version",
                      "fixed_prefix_sha256", "fixed_prefix_bytes")})
    result = report_prompts(prompts)
    result["requests"] = [dict(row, **measure) for row, measure in zip(rows, result["requests"])]
    return result


def _call_from_row(row: sqlite3.Row, columns: list[str]) -> ModelCall:
    values = dict(zip(columns, row))
    values["normalization_gaps"] = json.loads(values.pop("normalization_gaps_json") or "[]")
    raw = values.pop("raw_usage_json")
    values["raw_usage_json"] = json.loads(raw) if raw else None
    return ModelCall(**values)


def _cache_usage(calls: list[ModelCall]) -> dict[str, Any]:
    """Report measured cache usage without treating unknowns as zero."""
    measured: list[ModelCall] = []
    excluded_conflicts = 0
    excluded_unknown_input = 0
    excluded_unknown_cache = 0
    excluded_input_sum = 0
    for call in calls:
        if call.input_tokens is None:
            excluded_unknown_input += 1
        if call.cached_input_tokens is None:
            excluded_unknown_cache += 1
        if call.input_tokens is None or call.cached_input_tokens is None:
            if call.input_tokens is not None:
                excluded_input_sum += call.input_tokens
            continue
        gaps = set(call.normalization_gaps)
        if (call.cached_input_tokens > call.input_tokens or
                any(gap.startswith("conflict:input_tokens:") or
                    gap.startswith("conflict:cached_input_tokens:") for gap in gaps)):
            excluded_conflicts += 1
            excluded_input_sum += call.input_tokens
            continue
        measured.append(call)
    input_total = sum(c.input_tokens for c in measured)
    cached_total = sum(c.cached_input_tokens for c in measured)
    aggregate = aggregate_calls(calls)
    return {
        "physical_calls": len(calls),
        "measured_input_cache_calls": len(measured),
        "excluded_unknown_input_or_cache_calls": len(calls) - len(measured) - excluded_conflicts,
        "excluded_unknown_input_calls": excluded_unknown_input,
        "excluded_unknown_cache_calls": excluded_unknown_cache,
        "excluded_known_input_tokens": excluded_input_sum,
        "excluded_conflicting_input_cache_calls": excluded_conflicts,
        "input_tokens_measured_cohort": input_total if measured else None,
        "cached_input_tokens_measured_cohort": cached_total if measured else None,
        "cache_ratio": cached_total / input_total if measured and input_total else None,
        "all_calls": aggregate,
        "note": "ratio uses only calls with measured input and cache; bytes are eligibility evidence",
    }


def _scope(call: ModelCall) -> str:
    if call.provider == "codex_native" and call.transport == "codex_host_session":
        return "native_host_session"
    return call.transport or "unknown"


def _usage_partitions(calls: list[ModelCall], request_sequence: dict[str, Any]) -> dict[str, Any]:
    """Add request-order cohorts without combining distinct provider scopes."""
    sequences = [seq for seq in (request_sequence.get(c.request_id) for c in calls)
                 if isinstance(seq, int)]
    first = min(sequences) if sequences else None
    unknown = [c for c in calls if c.request_id is None or
               not isinstance(request_sequence.get(c.request_id), int)]
    result = _cache_usage(calls)
    result["first_request"] = _cache_usage(
        [c for c in calls if request_sequence.get(c.request_id) == first]) if first is not None else None
    result["later_requests"] = _cache_usage(
        [c for c in calls if isinstance(request_sequence.get(c.request_id), int)
         and request_sequence[c.request_id] > first]) if first is not None else None
    result["unknown_order"] = _cache_usage(unknown)
    result["first_request_sequence"] = first
    result["request_order_scope"] = "known_requests_within_group"
    return result


def report_sqlite(path: str | Path, game_id: str, model: str | None = None,
                  layout: str | None = None) -> dict[str, Any]:
    db = Path(path).resolve()
    if not db.is_file():
        raise FileNotFoundError(db)
    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    if conn.execute("SELECT 1 FROM games WHERE game_id=?", (game_id,)).fetchone() is None:
        conn.close()
        raise KeyError(game_id)
    call_columns = [row[1] for row in conn.execute("PRAGMA table_info(model_calls)")]
    required = set(ModelCall.__dataclass_fields__) - {"normalization_gaps"}
    available = required & set(call_columns)
    calls: list[ModelCall] = []
    if available:
        selected = [column for column in call_columns if column in available or column == "normalization_gaps_json"]
        for row in conn.execute("SELECT " + ",".join(selected) + " FROM model_calls WHERE game_id=? ORDER BY rowid", (game_id,)):
            calls.append(_call_from_row(row, selected))
    selected_calls = [c for c in calls if (model is None or c.requested_model == model)
                      and (layout is None or c.prompt_layout_version == layout)]
    selected_request_ids = {c.request_id for c in selected_calls if c.request_id}
    request_columns = {row[1] for row in conn.execute("PRAGMA table_info(model_requests)")}
    optional = lambda name: name if name in request_columns else "NULL AS " + name
    query = ("SELECT request_id,prompt_blob,payload_codec," + optional("prompt_layout_version") + ","
             + optional("fixed_prefix_sha256") + "," + optional("fixed_prefix_bytes")
             + " FROM model_requests WHERE game_id=?")
    params: list[Any] = [game_id]
    if model is not None or layout is not None:
        query += " AND request_id IN (" + ",".join("?" * len(selected_request_ids) or ["NULL"]) + ")"
        params.extend(sorted(selected_request_ids))
    query += " ORDER BY sequence,request_id"
    prompts: list[bytes] = []
    rows = []
    import zlib
    for row in conn.execute(query, params):
        raw = None if row[1] is None else (zlib.decompress(row[1]) if row[2] == "zlib" else row[1])
        prompts.append(raw)
        rows.append({"request_id": row[0], "prompt_layout_version": row[3],
                     "fixed_prefix_sha256": row[4], "fixed_prefix_bytes": row[5]})
    request_sequence = {row[0]: row[1] for row in conn.execute(
        "SELECT request_id,sequence FROM model_requests WHERE game_id=?", (game_id,))}
    conn.close()
    result = report_prompts(prompts)
    result["requests"] = [dict(row, **measure) for row, measure in zip(rows, result["requests"])]
    result["game_id"] = game_id
    ordered = sorted(((request_sequence.get(call.request_id), call) for call in selected_calls
                      if request_sequence.get(call.request_id) is not None), key=lambda item: (item[0], item[1].call_id))
    all_sequences = [seq for seq in request_sequence.values() if isinstance(seq, int)]
    first_sequence = min(all_sequences) if all_sequences else None
    groups: dict[tuple[Any, Any, Any, Any], list[ModelCall]] = {}
    for call in selected_calls:
        key = (call.requested_model or "unknown", call.prompt_layout_version or "unknown",
               call.transport or "unknown", _scope(call))
        groups.setdefault(key, []).append(call)
    result["cache_usage"] = _cache_usage(selected_calls)
    result["cache_usage"]["first_request"] = _cache_usage(
        [call for seq, call in ordered if seq == first_sequence]) if first_sequence is not None else None
    result["cache_usage"]["later_requests"] = _cache_usage(
        [call for seq, call in ordered if seq is not None and seq > first_sequence]) if first_sequence is not None else None
    unresolved = [call for call in selected_calls if call.request_id is None or
                  not isinstance(request_sequence.get(call.request_id), int)]
    result["cache_usage"]["unknown_order"] = _cache_usage(
        unresolved)
    result["cache_usage"]["first_request_sequence"] = first_sequence
    result["cache_usage"]["request_order_scope"] = "game_requests"
    result["cache_usage"]["groups"] = [
        {"model": key[0], "layout": key[1], "transport": key[2], "scope": key[3],
         "usage": _usage_partitions(members, request_sequence)} for key, members in sorted(groups.items(), key=str)]
    if len(groups) > 1:
        result["cache_usage"]["cache_ratio"] = None
        result["cache_usage"]["ratio_note"] = "ratio is reported separately for each model/layout/transport/scope group"
        for field in ("first_request", "later_requests", "unknown_order"):
            result["cache_usage"][field] = None
    result["calls"] = [{"call_id": c.call_id, "request_id": c.request_id,
                         "model": c.requested_model, "layout": c.prompt_layout_version,
                         "provider": c.provider, "reported_model": c.reported_model,
                         "transport": c.transport, "scope": _scope(c), "status": c.status,
                         "requested_affinity": c.requested_affinity,
                         "prompt_layout_source": c.prompt_layout_source,
                         "requested_reasoning_effort": c.requested_reasoning_effort,
                         "output_limit": c.output_limit, "elapsed_ms": c.elapsed_ms}
                        for c in selected_calls]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive")
    source.add_argument("--db")
    parser.add_argument("--game-id")
    parser.add_argument("--model")
    parser.add_argument("--layout")
    args = parser.parse_args(argv)
    if args.db and not args.game_id:
        parser.error("--game-id is required with --db")
    result = report_archive(args.archive) if args.archive else report_sqlite(args.db, args.game_id, args.model, args.layout)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
