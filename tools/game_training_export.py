"""Export reviewed decisions from the history catalog as reproducible JSONL."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import zlib
from pathlib import Path
from typing import Any

EXPORT_VERSION = 1

def _text(blob: bytes | None, codec: str | None) -> str | None:
    if blob is None:
        return None
    return (zlib.decompress(blob) if codec == "zlib" else blob).decode()

def assign_split(game_id: str, seed: int = 0) -> str:
    value = int(hashlib.sha256(f"{seed}:{game_id}".encode()).hexdigest()[:8], 16) % 100
    return "test" if value < 10 else ("validation" if value < 20 else "train")

def select_examples(conn: sqlite3.Connection, run_id: str,
                    split_seed: int = 0, rationale: bool = False) -> list[dict[str, Any]]:
    query = """SELECT d.request_id,r.game_id,r.prompt_blob,r.response_blob,r.payload_codec,
                      d.verdict,d.reason_codes_json
               FROM decision_evaluations d JOIN model_requests r USING(request_id)
               WHERE d.evaluation_run_id=? AND d.verdict='approve'
               ORDER BY r.game_id,r.sequence,r.request_id"""
    result = []
    for request_id, game_id, prompt_blob, response_blob, codec, verdict, reasons in conn.execute(query, (run_id,)):
        prompt = _text(prompt_blob, codec)
        response = _text(response_blob, codec)
        if not prompt or not response:
            continue
        example = {
            "id": request_id,
            "input": prompt,
            "output": response,
            "metadata": {"game_id": game_id, "request_id": request_id,
                         "split": assign_split(game_id, split_seed),
                         "evaluation_run_id": run_id, "verdict": verdict,
                         "reason_codes": json.loads(reasons)},
        }
        if rationale:
            # A rationale is exported only if it was actually stored.
            row = conn.execute("SELECT reasoning_blob,reasoning_source FROM model_requests WHERE request_id=?",
                               (request_id,)).fetchone()
            if not row or row[0] is None:
                continue
            example["rationale"] = _text(row[0], codec)
            example["metadata"]["reasoning_source"] = row[1]
        result.append(example)
    return result

def write_dataset_manifest(output: Path, examples: list[dict[str, Any]],
                           run_id: str, split_seed: int, selection: str) -> dict[str, Any]:
    manifest = {
        "export_version": EXPORT_VERSION, "evaluation_run_id": run_id,
        "split_seed": split_seed, "selection": selection,
        "count": len(examples),
        "example_ids": [e["id"] for e in examples],
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["output_sha256"] = hashlib.sha256(payload).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest

def export(conn: sqlite3.Connection, output: str, run_id: str,
           split_seed: int = 0, rationale: bool = False) -> dict[str, Any]:
    examples = select_examples(conn, run_id, split_seed, rationale)
    root = Path(output); root.mkdir(parents=True, exist_ok=True)
    for split in ("train", "validation", "test"):
        selected = [e for e in examples if e["metadata"]["split"] == split]
        (root / f"{split}.jsonl").write_text(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in selected))
    return write_dataset_manifest(root, examples, run_id, split_seed,
                                  "approved decision_evaluations joined to model_requests")

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True); parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True); parser.add_argument("--split-seed", type=int, default=0)
    parser.add_argument("--rationale", action="store_true")
    args = parser.parse_args(argv)
    conn = sqlite3.connect(args.db)
    print(json.dumps(export(conn, args.output, args.run_id, args.split_seed, args.rationale), sort_keys=True))
    conn.close(); return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
