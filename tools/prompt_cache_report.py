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


def report_sqlite(path: str | Path, game_id: str, model: str | None = None,
                  layout: str | None = None) -> dict[str, Any]:
    conn = sqlite3.connect(path)
    query = "SELECT request_id,prompt_blob,payload_codec,prompt_layout_version,fixed_prefix_sha256,fixed_prefix_bytes FROM model_requests WHERE game_id=?"
    params: list[Any] = [game_id]
    if model:
        query += " AND EXISTS (SELECT 1 FROM game_players p WHERE p.game_id=model_requests.game_id AND p.model_requested=?)"
        params.append(model)
    if layout:
        query += " AND prompt_layout_version=?"
        params.append(layout)
    query += " ORDER BY sequence,request_id"
    prompts: list[bytes] = []
    rows = []
    import zlib
    for row in conn.execute(query, params):
        if row[1] is None:
            continue
        raw = zlib.decompress(row[1]) if row[2] == "zlib" else row[1]
        prompts.append(raw)
        rows.append({"request_id": row[0], "prompt_layout_version": row[3],
                     "fixed_prefix_sha256": row[4], "fixed_prefix_bytes": row[5]})
    conn.close()
    result = report_prompts(prompts)
    result["requests"] = [dict(row, **measure) for row, measure in zip(rows, result["requests"])]
    result["game_id"] = game_id
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
