"""Bounded offline comparison for the Stack 4 recruiter fixture.

This executes explicit option batches against isolated copies of one tracked
checkpoint. Each case ends with an empty ``FinishWithGreedy`` boundary, so the
driver supplies exactly one real opponent turn. It is an evidence helper, not
a controller or a model-evaluation framework.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import select
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from .strategy_quality import UNIT_REGISTRY_COSTS



ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive"
DRIVER = Path(os.environ.get(
  "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver",
)).resolve()
NO_SWEEP_FINISH = {"action": "FinishWithGreedy", "groups": [], "holds": []}

# Launch defaults match the Stack 4 recruiter fixture exactly, so every
# existing call site (and its tests) keeps its original behavior when it
# passes no launch arguments. Stack 3's decision_capsule module supplies its
# own values for any other fixture instead of relying on these defaults.
DEFAULT_SCENARIO = "big_battle_6"
DEFAULT_FACTION0 = "undead"
DEFAULT_FACTION1 = "undead"
DEFAULT_GOLD = 300
DEFAULT_SEED = 4477
DEFAULT_LLM_SIDE = 0
DEFAULT_MAX_TURNS = 16
DEFAULT_INCREMENTAL_TURNS = True


def _read_json(path: Path) -> dict[str, Any]:
  return json.loads(path.read_text(encoding="utf-8"))


def _materialize(source: Path, destination: Path, *, scenario: str = DEFAULT_SCENARIO,
                 repo_root: Path = ROOT) -> Path:
  data = _read_json(source)
  board = repo_root / "scenarios" / scenario / "board.toml"
  if not board.is_file():
    raise RuntimeError(f"maintained {scenario} board is missing")
  data["board_path"] = str(board)
  data["save_state"]["board_path"] = str(board)
  encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
  side_turns = data.get("side_turns")
  revision = data.get("save_state", {}).get("state_revision")
  boundary = data.get("boundary")
  if (not isinstance(side_turns, int) or not isinstance(revision, int)
      or boundary != "model" or data.get("pending_opponent_turn") is not False):
    raise RuntimeError("fixture checkpoint has invalid model-boundary metadata")
  path = destination.with_name(
    f"{side_turns}-{revision}-{boundary}-{hashlib.sha256(encoded).hexdigest()}.json")
  path.write_bytes(encoded)
  return path


def _start(checkpoint: Path, checkpoint_dir: Path, *, driver: Path = DRIVER,
          scenario: str = DEFAULT_SCENARIO, faction0: str = DEFAULT_FACTION0,
          faction1: str = DEFAULT_FACTION1, gold: int = DEFAULT_GOLD,
          seed: int = DEFAULT_SEED, llm_side: int = DEFAULT_LLM_SIDE,
          max_turns: int = DEFAULT_MAX_TURNS,
          incremental_turns: bool = DEFAULT_INCREMENTAL_TURNS,
          repo_root: Path = ROOT) -> subprocess.Popen[bytes]:
  if not driver.is_file():
    raise RuntimeError("build the source-matched greedy_driver first")
  argv = [str(driver), "--scenario", scenario, "--faction0", faction0,
          "--faction1", faction1, "--gold", str(gold), "--seed", str(seed),
          "--llm-side", str(llm_side), "--max-turns", str(max_turns)]
  if incremental_turns:
    argv.append("--incremental-turns")
  argv += ["--checkpoint-dir", str(checkpoint_dir), "--resume-checkpoint", str(checkpoint)]
  return subprocess.Popen(
    argv,
    cwd=repo_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, bufsize=0,
  )


def _send(process: subprocess.Popen[bytes], payload: Any) -> None:
  if process.stdin is None:
    raise RuntimeError("driver stdin is closed")
  process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
  process.stdin.flush()


def _read_until(process: subprocess.Popen[bytes], kind: str, *, timeout: float = 45.0,
                accept_game_end: bool = False) -> list[dict[str, Any]]:
  records: list[dict[str, Any]] = []
  deadline = time.monotonic() + timeout
  while True:
    if process.stdout is None:
      raise RuntimeError(f"driver has no stdout before {kind}")
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
      raise RuntimeError(f"driver timed out before {kind}")
    line = process.stdout.readline()
    if not line:
      raise RuntimeError(f"driver closed before {kind}")
    record = json.loads(line)
    records.append(record)
    if record.get("type") == kind or (accept_game_end and record.get("type") == "game_end"):
      return records


def _query(process: subprocess.Popen[bytes], payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
  _send(process, payload)
  records = _read_until(process, "status")
  return records[-1], records


def _close(process: subprocess.Popen[bytes]) -> None:
  if process.poll() is None:
    process.terminate()
  try:
    process.wait(timeout=5)
  except subprocess.TimeoutExpired:
    process.kill()
    process.wait(timeout=5)
  for stream in (process.stdin, process.stdout, process.stderr):
    if stream is not None:
      stream.close()


def _valid_state(state: dict[str, Any] | None) -> bool:
  if not isinstance(state, dict) or not isinstance(state.get("units"), list):
    return False
  ids: set[int] = set()
  for unit in state["units"]:
    if (not isinstance(unit, dict) or not isinstance(unit.get("id"), int)
        or isinstance(unit.get("id"), bool)
        or not isinstance(unit.get("faction"), int)
        or unit["faction"] not in (0, 1)
        or unit["id"] in ids):
      return False
    ids.add(unit["id"])
  if not isinstance(state.get("terrain"), list):
    return False
  for tile in state["terrain"]:
    if (not isinstance(tile, dict) or not isinstance(tile.get("col"), int)
        or isinstance(tile.get("col"), bool)
        or not isinstance(tile.get("row"), int)
        or isinstance(tile.get("row"), bool)):
      return False
    if tile.get("terrain_id") == "village" and "owner" not in tile:
      return False
  return True


def _state_units(state: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
  if not isinstance(state, dict) or not isinstance(state.get("units"), list):
    return {}
  return {
    unit["id"]: unit for unit in state.get("units", [])
    if isinstance(unit, dict) and isinstance(unit.get("id"), int)
    and not isinstance(unit.get("id"), bool)
  }


def _ownership(state: dict[str, Any] | None) -> dict[tuple[int, int], Any] | None:
  if not isinstance(state, dict) or not isinstance(state.get("terrain"), list):
    return None
  villages = {}
  for tile in state["terrain"]:
    if not isinstance(tile, dict) or tile.get("terrain_id") != "village":
      continue
    if (not isinstance(tile.get("col"), int) or isinstance(tile.get("col"), bool)
        or not isinstance(tile.get("row"), int) or isinstance(tile.get("row"), bool)
        or "owner" not in tile):
      return None
    villages[(tile["col"], tile["row"])] = tile["owner"]
  return villages


def _events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
  result = []
  for record in records:
    if record.get("type") != "events":
      continue
    result.extend(event for event in record.get("events", []) if isinstance(event, dict))
  return result


def _latest_checkpoint(checkpoint_dir: Path, records: list[dict[str, Any]]) -> dict[str, Any] | None:
  candidates = []
  for record in records:
    if record.get("type") != "checkpoint":
      continue
    path_value = record.get("path")
    path = checkpoint_dir / path_value if isinstance(path_value, str) else checkpoint_dir / ""
    if path.is_file() and record.get("pending_opponent_turn") is False:
      try:
        raw = path.read_bytes()
        data = json.loads(raw)
        save_state = data.get("save_state")
        if not isinstance(save_state, dict):
          continue
        digest = hashlib.sha256(raw).hexdigest()
        if record.get("digest") != digest:
          continue
        if data.get("boundary") != "model":
          continue
        if (record.get("boundary") != data.get("boundary")
            or record.get("side_turns") != data.get("side_turns")):
          continue
        if data.get("pending_opponent_turn") is not False:
          continue
        if not isinstance(data.get("side_turns"), int) or data["side_turns"] < 0:
          continue
        if not isinstance(save_state.get("state_revision"), int):
          continue
        if save_state["state_revision"] != record.get("state_revision"):
          continue
      except (OSError, TypeError, ValueError):
        continue
      candidates.append((data["side_turns"], save_state["state_revision"], path, raw, data))
  if not candidates:
    return None
  _side_turns, _revision, path, raw, data = max(candidates, key=lambda item: (item[0], item[1]))
  return {
    "path": path.name,
    "sha256": hashlib.sha256(raw).hexdigest(),
    "state_revision": data.get("save_state", {}).get("state_revision"),
    "side_turns": data.get("side_turns"),
    "rng_state": data.get("save_state", {}).get("rng_state"),
    "save_state": data.get("save_state"),
  }


def _terminal_state(records: list[dict[str, Any]]) -> dict[str, Any] | None:
  for record in reversed(records):
    if record.get("type") != "game_end" or not isinstance(record.get("state"), dict):
      continue
    state = copy.deepcopy(record["state"])
    state.setdefault("side_turns", record.get("side_turns"))
    state.setdefault("state_revision", record.get("state_revision"))
    return state
  return None


def _case_result(case: str, option_ids: list[str], reference: dict[str, Any], *,
                 fixture: Path = FIXTURE, driver: Path = DRIVER,
                 scenario: str = DEFAULT_SCENARIO, faction0: str = DEFAULT_FACTION0,
                 faction1: str = DEFAULT_FACTION1, gold: int = DEFAULT_GOLD,
                 seed: int = DEFAULT_SEED, llm_side: int = DEFAULT_LLM_SIDE,
                 max_turns: int = DEFAULT_MAX_TURNS,
                 incremental_turns: bool = DEFAULT_INCREMENTAL_TURNS,
                 repo_root: Path = ROOT) -> dict[str, Any]:
  with tempfile.TemporaryDirectory(prefix="norrust-tactical-") as td:
    root = Path(td)
    checkpoint_dir = root / "checkpoints"
    checkpoint_dir.mkdir()
    checkpoint = _materialize(fixture / "checkpoint.json", root / "checkpoint.json",
                              scenario=scenario, repo_root=repo_root)
    process = _start(checkpoint, checkpoint_dir, driver=driver, scenario=scenario,
                     faction0=faction0, faction1=faction1, gold=gold, seed=seed,
                     llm_side=llm_side, max_turns=max_turns,
                     incremental_turns=incremental_turns, repo_root=repo_root)
    records: list[dict[str, Any]] = []
    try:
      initial_records = _read_until(process, "state")
      records.extend(initial_records)
      initial_state = initial_records[-1]
      revision = initial_state["state_revision"]
      metadata = _read_json(fixture / "metadata.json")
      routine_reply, query_records = _query(process, {
        "action": "Query", "what": "routine_next", "state_revision": revision,
        "policy": metadata["policy"], "progress": metadata["progress"],
      })
      records.extend(query_records)
      if (routine_reply.get("ok") is not True
          or not isinstance(routine_reply.get("body"), dict)
          or not isinstance(routine_reply["body"].get("evidence"), dict)):
        raise RuntimeError(f"{case}: routine_next returned an invalid response")
      evidence = routine_reply["body"]["evidence"]
      evidence = copy.deepcopy(evidence)
      options = evidence.get("options")
      if not isinstance(options, list) or any(not isinstance(option, dict)
                                               or not isinstance(option.get("option_id"), str)
                                               or not isinstance(option.get("actions"), list)
                                               for option in options):
        raise RuntimeError(f"{case}: routine_next evidence has no valid options")
      by_id = {option["option_id"]: option for option in options}
      if option_ids:
        if any(option_id not in by_id for option_id in option_ids):
          raise RuntimeError(f"{case}: frozen option is absent from current packet")
        orders = [action for option_id in option_ids for action in by_id[option_id]["actions"]]
      else:
        orders = []
      if case == "always_first":
        if not options:
          raise RuntimeError("always-first case has no current option")
        first_id = options[0]["option_id"]
        if option_ids != [first_id]:
          raise RuntimeError("always-first case was not built from the first issued option")
      submitted = orders + [copy.deepcopy(NO_SWEEP_FINISH)]
      validation, validation_records = _query(process, {
        "action": "Query", "what": "validate_batch",
        "state_revision": revision, "orders": submitted,
      })
      records.extend(validation_records)
      if validation.get("body", {}).get("valid") is not True:
        raise RuntimeError(f"{case}: frozen batch including NO_SWEEP_FINISH is invalid: {validation}")
      _send(process, submitted)
      post_records = _read_until(process, "state", accept_game_end=True)
      records.extend(post_records)
      submit_status = next(
        (record for record in reversed(post_records)
         if record.get("type") == "status" and "committed" in record), None)
      # Keep reading until the model-side state after the opponent boundary is
      # visible. A postbatch checkpoint alone is not opponent evidence.
      final_checkpoint = _latest_checkpoint(checkpoint_dir, records)
      deadline = time.monotonic() + 120
      while True:
        greedy_events = [event for event in _events(records) if event.get("source") == "greedy"]
        terminal = _terminal_state(records)
        terminal_reason = next(
          (line.get("reason") for line in reversed(records)
           if line.get("type") == "game_end"), None)
        if (terminal is not None
                and terminal_reason not in {"max_turns", "timeout", "infrastructure_failure"}
                and (final_checkpoint is None
                     or terminal.get("side_turns", -1) > final_checkpoint.get("side_turns", -1))):
          final_checkpoint = {
            "embedded_terminal": True,
            "state_revision": terminal.get("state_revision"),
            "side_turns": terminal.get("side_turns"),
            "rng_state": terminal.get("rng_state"),
            "save_state": terminal.get("save_state"),
          }
        if (greedy_events and final_checkpoint
                and final_checkpoint.get("side_turns", -1) >= reference["side_turns"] + 2
                and any(record.get("type") == "state"
                        and record.get("state_revision") == final_checkpoint.get("state_revision")
                        and record.get("active_faction") == 0
                        for record in records)):
          break
        if time.monotonic() >= deadline:
          raise RuntimeError(f"{case}: incomplete opponent horizon")
        if process.stdout is None or not select.select([process.stdout], [], [], deadline - time.monotonic())[0]:
          raise RuntimeError(f"{case}: timed out waiting for opponent horizon")
        line = process.stdout.readline()
        if not line:
          break
        record = json.loads(line)
        records.append(record)
        final_checkpoint = _latest_checkpoint(checkpoint_dir, records)
        if record.get("type") == "game_end":
          break
      states = [record for record in records if record.get("type") == "state"]
      terminal_state = _terminal_state(records)
      if terminal_state is not None:
        states.append(terminal_state)
      controlled_states = [record for record in states if record.get("active_faction") == 0]
      final_state = max(controlled_states, key=lambda record: record.get("state_revision", -1), default=None)
      terminal_record = next((record for record in reversed(records)
                              if record.get("type") == "game_end"), None)
      if (terminal_record and terminal_record.get("reason") == "winner"
          and terminal_state and (final_checkpoint is None
                                  or terminal_state.get("side_turns", -1)
                                  > final_checkpoint.get("side_turns", -1))):
        final_checkpoint = {
          "embedded_terminal": True,
          "state_revision": terminal_state.get("state_revision"),
          "side_turns": terminal_state.get("side_turns"),
          "rng_state": terminal_state.get("rng_state"),
          "save_state": terminal_state.get("save_state"),
        }
      terminal_complete = bool(
        terminal_record and terminal_record.get("reason") == "winner"
        and final_checkpoint and final_checkpoint.get("embedded_terminal")
        and final_checkpoint.get("side_turns", -1) >= reference["side_turns"] + 2
        and terminal_state and _valid_state(terminal_state))
      if terminal_complete:
        final_state = terminal_state
      events = _events(records)
      greedy_events = [event for event in events if event.get("source") == "greedy"]
      normal_complete = bool(
        final_checkpoint and not final_checkpoint.get("embedded_terminal")
        and final_checkpoint.get("side_turns") == reference["side_turns"] + 2
        and final_state and final_state.get("active_faction") == 0
        and final_state.get("state_revision") == final_checkpoint.get("state_revision")
        and _valid_state(final_state) and _valid_state(initial_state)
        and greedy_events and submit_status
        and submit_status.get("ok") is True
        and submit_status.get("committed") is True)
      terminal_complete = bool(terminal_complete and submit_status
                               and submit_status.get("ok") is True
                               and submit_status.get("committed") is True
                               and greedy_events)
      complete_horizon = normal_complete or terminal_complete
      initial_units = _state_units(initial_state)
      final_units = _state_units(final_state) if final_state else {}
      losses = ({
        "controlled": sorted(unit_id for unit_id, unit in initial_units.items()
                              if unit.get("faction") == 0 and unit_id not in final_units),
        "opponent": sorted(unit_id for unit_id, unit in initial_units.items()
                            if unit.get("faction") == 1 and unit_id not in final_units),
      } if complete_horizon else "unknown")
      loss_costs = "unknown"
      if complete_horizon and isinstance(losses, dict):
        loss_costs = {}
        for side in ("controlled", "opponent"):
          side_costs = []
          for unit_id in losses[side]:
            unit = initial_units.get(unit_id)
            cost = UNIT_REGISTRY_COSTS.get(unit.get("def_id")) if unit else None
            if not isinstance(cost, int):
              side_costs = "unknown"
              break
            side_costs.append({"unit_id": unit_id, "def_id": unit["def_id"], "cost": cost})
          loss_costs[side] = side_costs
      initial_owners = _ownership(initial_state)
      final_owners = _ownership(final_state) if final_state else {}
      ownership_changes = [
        {"col": col, "row": row, "before": initial_owners[(col, row)], "after": final_owners[(col, row)]}
        for col, row in sorted(initial_owners or {})
        if final_owners.get((col, row)) != initial_owners[(col, row)]
      ] if complete_horizon and initial_owners is not None and final_owners is not None else "unknown"
      recruiter = final_units.get(reference["threatened_recruiter_id"]) if complete_horizon else None
      return {
        "case": case,
        "option_ids": option_ids,
        "submitted_actions": submitted,
        "validity": validation.get("body", {}).get("valid") if validation else False,
        "committed": submit_status.get("committed") if submit_status else None,
        "submit_status": {
          "ok": submit_status.get("ok") if submit_status else None,
          "committed": submit_status.get("committed") if submit_status else None,
        },
        "recruiter": {
          "survived": recruiter is not None if complete_horizon else "unknown",
          "hp": recruiter.get("hp") if recruiter else (0 if complete_horizon else "unknown"),
        },
        "known_material_losses": losses,
        "known_material_loss_costs": loss_costs,
        "ownership_changes": ownership_changes,
        "evidence_coverage": {
          "initial_state": bool(initial_state),
          "opponent_events": bool(greedy_events),
          "final_state_after_opponent": complete_horizon,
          "ownership": bool(complete_horizon and initial_owners is not None
                             and final_owners is not None),
          "terminal": ({
            "reason": terminal_record.get("reason"),
            "winner": terminal_record.get("winner"),
          } if terminal_record else None),
        },
        "horizon": {
          "initial_side_turns": reference["side_turns"],
          "final_side_turns": final_checkpoint.get("side_turns") if final_checkpoint else None,
          "greedy_event_count": len(greedy_events),
        },
        "checkpoint": final_checkpoint,
      }
    finally:
      _close(process)


def run_comparison(*, fixture: Path = FIXTURE, driver: Path = DRIVER,
                   scenario: str = DEFAULT_SCENARIO, faction0: str = DEFAULT_FACTION0,
                   faction1: str = DEFAULT_FACTION1, gold: int = DEFAULT_GOLD,
                   seed: int = DEFAULT_SEED, llm_side: int = DEFAULT_LLM_SIDE,
                   max_turns: int = DEFAULT_MAX_TURNS,
                   incremental_turns: bool = DEFAULT_INCREMENTAL_TURNS,
                   repo_root: Path = ROOT) -> dict[str, Any]:
  reference = _read_json(fixture / "stack4_reference.json")
  source_checkpoint = fixture / reference["source_checkpoint"]
  source_metadata = fixture / "metadata.json"
  if hashlib.sha256(source_checkpoint.read_bytes()).hexdigest() != reference["source_checkpoint_sha256"]:
    raise RuntimeError("fixture checkpoint provenance hash does not match stack4_reference.json")
  if hashlib.sha256(source_metadata.read_bytes()).hexdigest() != reference["source_metadata_sha256"]:
    raise RuntimeError("fixture metadata provenance hash does not match stack4_reference.json")
  driver_sha256 = hashlib.sha256(driver.read_bytes()).hexdigest() if driver.is_file() else None
  alternatives = reference["alternatives"]
  cases = [
    ("relocation_pressure", alternatives["relocation_pressure"]["option_ids"]),
    ("pressure", alternatives["pressure"]["option_ids"]),
    ("no_sweep", []),
    ("always_first", [reference["option_ids"][0]]),
  ]
  results = [_case_result(name, ids, reference, fixture=fixture, driver=driver,
                          scenario=scenario, faction0=faction0, faction1=faction1,
                          gold=gold, seed=seed, llm_side=llm_side, max_turns=max_turns,
                          incremental_turns=incremental_turns, repo_root=repo_root)
             for name, ids in cases]
  return {
    "fixture": str(fixture.relative_to(repo_root)),
    "source_checkpoint_sha256": reference["source_checkpoint_sha256"],
    "source_metadata_sha256": reference["source_metadata_sha256"],
    "driver_path": str(driver),
    "driver_sha256": driver_sha256,
    "state_revision": reference["state_revision"],
    "horizon": "one controlled boundary plus one actual Greedy opponent turn",
    "cases": results,
  }


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--output", type=Path, help="write JSON report here instead of stdout")
  args = parser.parse_args(argv)
  report = run_comparison()
  encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
  if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
  else:
    print(encoded, end="")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
