"""Build the required evidence packet, decisions log, scores, and review packet for recruiter survival.

Produces:
- decisions.jsonl
- scores.json
- evidence-index.json
- review-packet.json
- HANDOFF.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from . import game_history, match_report, strategy_quality as sq

REPO_ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str | None:
  if not path.is_file():
    return None
  return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_decisions(cell_dir: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Extract decisions.jsonl rows from a cell's match records."""
  rows = []
  last_state = None
  recruiter_id = 1
  for r in records:
    if r.get("type") == "driver" and isinstance(r.get("line"), dict):
      line = r["line"]
      if line.get("type") == "state":
        last_state = line
        units = line.get("units", [])
        recruiter = next((u for u in units if u.get("faction") == 0 and (u.get("can_recruit") or "leader" in u.get("abilities", []))), None)
        if recruiter:
          recruiter_id = recruiter.get("id", 1)

    if r.get("type") == "forwarded_orders":
      orders = r.get("orders", [])
      annotation = r.get("decision_annotation") or {}
      recruiter_before = None
      if last_state:
        recruiter_unit = next((u for u in last_state.get("units", []) if u.get("id") == recruiter_id), None)
        if recruiter_unit:
          recruiter_before = {
            "unit_id": recruiter_id,
            "hp": recruiter_unit.get("hp"),
            "col": recruiter_unit.get("col"),
            "row": recruiter_unit.get("row"),
            "alive": recruiter_unit.get("hp", 0) > 0,
          }
      rows.append({
        "cell_id": cell_dir.name,
        "revision": last_state.get("state_revision") if last_state else None,
        "side_turn": last_state.get("side_turns") if last_state else None,
        "actor": recruiter_id,
        "orders": orders,
        "annotation": annotation,
        "recruiter_before": recruiter_before,
      })
  return rows


def build_evidence_index(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
  """Build index of all cell artifacts, hashes, and files."""
  index: dict[str, Any] = {
    "run_dir": str(run_dir),
    "resolved_at": manifest.get("resolved_at"),
    "cells": {},
  }
  for cell in manifest.get("cells", []):
    cid = cell["id"]
    cdir = run_dir / cid
    cell_entry: dict[str, Any] = {
      "cell_id": cid,
      "position_id": cell.get("position_id"),
      "reasoning_effort": cell.get("reasoning_effort"),
      "files": {},
    }
    for fname in ("match.ndjson", "run_status.json", "identity.json", "client_stderr.log", "source_checkpoint.json", "usage.ndjson", "request_context.json"):
      fpath = cdir / fname
      if fpath.is_file():
        cell_entry["files"][fname] = {
          "path": str(fpath),
          "size": fpath.stat().st_size,
          "sha256": file_sha256(fpath),
        }
      else:
        cell_entry["files"][fname] = None
    index["cells"][cid] = cell_entry
  return index


def build_scores(run_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
  """Build scores.json for all cells in run_dir."""
  scores = {}
  for cell in manifest.get("cells", []):
    cid = cell["id"]
    cdir = run_dir / cid
    match_file = cdir / "match.ndjson"
    pos_id = cell.get("position_id", "")
    if not match_file.is_file():
      scores[cid] = {
        "cell_id": cid,
        "status": "not_run",
        "passed": False,
        "position_id": pos_id,
        "reasoning_effort": cell.get("reasoning_effort"),
        "metric_vector": None,
      }
      continue

    records = match_report.load_records(match_file)
    try:
      score = sq.score_cell(pos_id, records)
      scores[cid] = {
        "cell_id": cid,
        "status": score.get("status", "scored"),
        "passed": bool(score.get("passed")),
        "position_id": pos_id,
        "reasoning_effort": cell.get("reasoning_effort"),
        "metric_vector": score,
      }
    except Exception as exc:
      scores[cid] = {
        "cell_id": cid,
        "status": "unscored",
        "unscored_reason": str(exc),
        "passed": False,
        "position_id": pos_id,
        "reasoning_effort": cell.get("reasoning_effort"),
        "metric_vector": None,
      }
  return scores


def build_review_packet(run_dir: Path, manifest: dict[str, Any], scores: dict[str, Any], catalog_path: Path | None = None) -> dict[str, Any]:
  """Compile review-packet.json comparing low and high effort arms across the 4 positions."""
  positions: dict[str, dict[str, Any]] = {}
  for cell in manifest.get("cells", []):
    cid = cell["id"]
    pos_id = cell.get("position_id", "")
    effort = cell.get("reasoning_effort", "")
    cell_score = scores.get(cid, {})
    pos_dict = positions.setdefault(pos_id, {})
    pos_dict[effort] = {
      "cell_id": cid,
      "passed": cell_score.get("passed", False),
      "status": cell_score.get("status", "unknown"),
      "metric_vector": cell_score.get("metric_vector"),
    }

  if manifest.get("experiment_kind") == "observation":
    cell_summaries = {}
    for cell in manifest.get("cells", []):
      cid = cell["id"]
      cell_score = scores.get(cid, {})
      cell_summaries[cid] = {
        "cell_id": cid,
        "seed": cell.get("seed"),
        "reasoning_effort": cell.get("reasoning_effort"),
        "passed": cell_score.get("passed", False),
        "status": cell_score.get("status", "unknown"),
        "metric_vector": cell_score.get("metric_vector"),
      }
    return {
      "experiment_kind": "observation",
      "cells": cell_summaries,
      "objective": manifest.get("objective"),
      "decision": "baseline_observations_complete",
      "recommendation": "Preserve historical evidence and baseline observations; no candidate justified by Stack 2 screen",
    }

  # High passes at least two defensive fixtures low fails, loses none that low passes, and passes quiet control
  low_passes = {p: positions[p].get("low", {}).get("passed", False) for p in positions}
  high_passes = {p: positions[p].get("high", {}).get("passed", False) for p in positions}

  defensive_positions = [
    "fixture_1_seed_4477_defensive",
    "fixture_2_seed_7731_defensive",
    "fixture_3_late_emergency",
  ]
  quiet_pos = "fixture_4_quiet_control"

  high_gains = sum(1 for p in defensive_positions if high_passes.get(p) and not low_passes.get(p))
  high_losses = sum(1 for p in defensive_positions if low_passes.get(p) and not high_passes.get(p))
  quiet_pass = high_passes.get(quiet_pos, False)

  if all(low_passes.values()) and all(high_passes.values()):
    decision = "both_arms_pass"
    recommendation = "Proceed to full games without tactical changes"
  elif high_gains >= 2 and high_losses == 0 and quiet_pass:
    decision = "high_effort_promising"
    recommendation = "High is a candidate for Stack 4 comparison"
  elif not any(low_passes.values()) and not any(high_passes.values()):
    decision = "both_arms_weak"
    recommendation = "Model/prompt decision weakness; check menu and fact delivery"
  else:
    decision = "mixed_or_neutral"
    recommendation = "Report results plainly; evaluate specific menu/fact causes"

  return {
    "positions": positions,
    "low_passes": low_passes,
    "high_passes": high_passes,
    "high_gains_over_low": high_gains,
    "high_losses_to_low": high_losses,
    "quiet_control_passed": quiet_pass,
    "decision": decision,
    "recommendation": recommendation,
  }


def generate_packet(run_dir: Path, catalog_path: Path | None = None) -> None:
  """Generate all evidence packet files in run_dir."""
  manifest_path = run_dir / "manifest.json"
  if not manifest_path.is_file():
    raise FileNotFoundError(f"Missing manifest.json in {run_dir}")
  manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

  # 1. decisions.jsonl
  decisions_path = run_dir / "decisions.jsonl"
  with decisions_path.open("w", encoding="utf-8") as dfile:
    for cell in manifest.get("cells", []):
      cdir = run_dir / cell["id"]
      mfile = cdir / "match.ndjson"
      if mfile.is_file():
        recs = match_report.load_records(mfile)
        for row in extract_decisions(cdir, recs):
          dfile.write(json.dumps(row) + "\n")

  # 2. evidence-index.json
  evidence_index = build_evidence_index(run_dir, manifest)
  (run_dir / "evidence-index.json").write_text(json.dumps(evidence_index, indent=2, sort_keys=True) + "\n")

  # 3. scores.json
  scores = build_scores(run_dir, manifest)
  (run_dir / "scores.json").write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")

  # 4. review-packet.json
  review_packet = build_review_packet(run_dir, manifest, scores, catalog_path=catalog_path)
  (run_dir / "review-packet.json").write_text(json.dumps(review_packet, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Build evidence packet for recruiter survival run")
  parser.add_argument("--run-dir", type=Path, required=True, help="Path to experiment run directory")
  parser.add_argument("--catalog", type=Path, help="Path to SQLite catalog")
  args = parser.parse_args(argv)

  generate_packet(args.run_dir, catalog_path=args.catalog)
  print(f"Evidence packet successfully generated in {args.run_dir}")
  return 0


if __name__ == "__main__":
  import sys
  sys.exit(main())
