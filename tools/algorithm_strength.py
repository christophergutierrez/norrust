"""Frozen, resumable gameplay evaluation for the built-in algorithms.

The official runner always evaluates coordinated as the controlled algorithm.
It writes a frozen manifest, one durable attempt journal, isolated process logs,
recorded engine traces, and atomically replaced results. ``--check`` validates
that evidence without launching games.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FACTIONS = ("loyalists", "rebels", "northerners", "undead")
DEFAULT_OPPONENTS = ("greedy", "greedy-look-ahead")
CONTROLLED_ALGORITHM = "coordinated"
SCHEMA_VERSION = 2
WIN_RATE_THRESHOLDS = {"development": 0.80, "heldout": 0.80}
_JOURNAL_LOCK = threading.Lock()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def source_identity(root: Path = ROOT) -> dict[str, str]:
    """Require a committed source tree so a run can be repeated exactly."""
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError("source checkout is dirty; commit or remove source changes before freezing a run")
    return {"commit": _git(root, "rev-parse", "HEAD"), "tree": _git(root, "rev-parse", "HEAD^{tree}")}


def data_sha256(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "data").rglob("*")):
        if path.is_file():
            rel = path.relative_to(root / "data").as_posix().encode()
            digest.update(len(rel).to_bytes(4, "big")); digest.update(rel)
            content = path.read_bytes()
            digest.update(len(content).to_bytes(8, "big")); digest.update(content)
    return digest.hexdigest()


def _cell(cell_id: str, faction: str, opponent: str, side: int, first: str,
          gold: int, seed: int, cap: int) -> dict[str, Any]:
    return {"cell_id": cell_id, "scenario": "big_battle_6", "faction": faction,
            "opponent": opponent, "controlled_algorithm": CONTROLLED_ALGORITHM,
            "controlled_side": side, "first": first, "gold": gold,
            "second_gold": 0, "seed": seed, "max_side_turns": cap,
            "recruit1_policy": "first-affordable", "recruit2_policy": "first-affordable",
            "threads": 1}


def load_mechanics_schedule(path: Path, through_stack: int = 7) -> list[dict[str, Any]]:
    """Load the small tracked mechanics manifest into ordinary game cells."""
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != 1 or not isinstance(payload.get("fixtures"), list):
        raise ValueError("unsupported mechanics fixture manifest")
    schedule = []
    for fixture in payload["fixtures"]:
        if not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str):
            raise ValueError("mechanics fixture lacks an id")
        if int(fixture.get("introduced_stack", 99)) > through_stack:
            continue
        required = {"scenario", "faction", "opponent", "controlled_algorithm", "controlled_side",
                    "first", "gold", "second_gold", "seed", "max_side_turns",
                    "recruit1_policy", "recruit2_policy", "threads", "assertions"}
        missing = sorted(required - fixture.keys())
        if missing:
            raise ValueError(f"{fixture['id']}: missing fields {missing}")
        if fixture["controlled_algorithm"] != CONTROLLED_ALGORITHM or fixture["threads"] != 1:
            raise ValueError(f"{fixture['id']}: mechanics fixture treatment is not pinned")
        cell = dict(fixture)
        cell["cell_id"] = fixture["id"]
        schedule.append(cell)
    if not schedule:
        raise ValueError("mechanics manifest has no fixtures through the requested stack")
    if len({cell["cell_id"] for cell in schedule}) != len(schedule):
        raise ValueError("mechanics manifest contains duplicate fixture ids")
    return schedule


def build_schedule(*, suite: str = "screen", base_seed: int = 26001,
                   gold: int = 300, max_side_turns: int = 200,
                   mechanics_manifest: Path | None = None,
                   through_stack: int = 7) -> list[dict[str, Any]]:
    """Build the fixed suite schedule; ordering is stable and part of its contract."""
    if suite == "smoke":
        return [
            _cell("smoke-greedy-side0-first1", "loyalists", "greedy", 0, "team1", 300, base_seed, 200),
            _cell("smoke-greedy-side1-first1", "loyalists", "greedy", 1, "team1", 300, base_seed + 1, 200),
            _cell("smoke-lookahead-side0-first2", "loyalists", "greedy-look-ahead", 0, "team2", 300, base_seed + 2, 200),
            _cell("smoke-lookahead-side1-first2", "loyalists", "greedy-look-ahead", 1, "team2", 300, base_seed + 3, 200),
        ]
    if suite == "screen":
        cells = []
        index = 0
        for faction in DEFAULT_FACTIONS:
            for opponent in DEFAULT_OPPONENTS:
                for side in (0, 1):
                    for first in ("team1", "team2"):
                        cells.append(_cell(f"{faction}-{opponent}-side{side}-{first}", faction,
                                           opponent, side, first, gold, base_seed + index, max_side_turns))
                        index += 1
        return cells
    if suite in ("development", "heldout"):
        cells = []
        seeds_per_faction = 4 if suite == "development" else 8
        index = 0
        for faction in DEFAULT_FACTIONS:
            for seed_index in range(seeds_per_faction):
                for side in (0, 1):
                    for first in ("team1", "team2"):
                        for starting_gold in (250, 350):
                            for opponent in DEFAULT_OPPONENTS:
                                cells.append(_cell(
                                    f"{suite}-{faction}-seed{seed_index}-side{side}-{first}-g{starting_gold}-{opponent}",
                                    faction, opponent, side, first, starting_gold,
                                    base_seed + index, max_side_turns))
                                index += 1
        return cells
    if suite == "mechanics":
        if mechanics_manifest is None:
            raise ValueError("mechanics suite requires the tracked fixture manifest")
        return load_mechanics_schedule(mechanics_manifest, through_stack)
    raise ValueError(f"unknown suite: {suite}")


def command_for(cell: Mapping[str, Any], binary: Path, record_dir: Path | None = None) -> list[str]:
    if cell.get("controlled_algorithm") != CONTROLLED_ALGORITHM:
        raise ValueError("official suites require coordinated as controlled algorithm")
    if int(cell["controlled_side"]) == 0:
        ai1, ai2 = CONTROLLED_ALGORITHM, str(cell["opponent"])
    else:
        ai1, ai2 = str(cell["opponent"]), CONTROLLED_ALGORITHM
    command = [str(binary), "--scenario", str(cell["scenario"]),
               "--team1", str(cell["faction"]), "--team2", str(cell["faction"]),
               "--ai1", ai1, "--ai2", ai2, "--games", "1", "--seed", str(cell["seed"]),
               "--threads", "1", "--gold", str(cell["gold"]),
               "--second-gold", str(cell["second_gold"]), "--first", str(cell["first"]),
               "--max-side-turns", str(cell["max_side_turns"]),
               "--recruit1-policy", str(cell["recruit1_policy"]),
               "--recruit2-policy", str(cell["recruit2_policy"]), "--json"]
    if record_dir is not None:
        command += ["--record-dir", str(record_dir)]
    return command


def _result_lines(stdout: str) -> list[dict[str, Any]]:
    rows = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("type") == "self_play_result":
            rows.append(value)
    return rows


def _expected_algorithms(cell: Mapping[str, Any]) -> list[str]:
    if cell["controlled_side"] == 0:
        return [CONTROLLED_ALGORITHM, cell["opponent"]]
    return [cell["opponent"], CONTROLLED_ALGORITHM]


def validate_engine_result(cell: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """Validate the real recorder row against its frozen schedule cell."""
    expected = {
        "raw_seed": int(cell["seed"]), "scenario": cell["scenario"],
        "factions": [cell["faction"], cell["faction"]],
        "algorithms": _expected_algorithms(cell),
        "recruitment_policies": [cell["recruit1_policy"], cell["recruit2_policy"]],
        "first_side": 0 if cell["first"] == "team1" else 1,
        "second_gold": int(cell["second_gold"]),
        "side_turn_cap": int(cell["max_side_turns"]),
        "starting_gold": [int(cell["gold"]), int(cell["gold"])],
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise ValueError(f"{cell['cell_id']}: result {key} mismatch: {result.get(key)!r} != {value!r}")
    if result.get("effective_seed") != _mix_seed(int(cell["seed"])):
        raise ValueError(f"{cell['cell_id']}: effective seed mismatch")
    turns = result.get("completed_side_turns")
    if not isinstance(turns, int) or not 1 <= turns <= int(cell["max_side_turns"]):
        raise ValueError(f"{cell['cell_id']}: invalid completed turn count")
    winner, reason = result.get("winner_side"), result.get("termination_reason")
    if reason == "winner":
        if winner not in (0, 1):
            raise ValueError(f"{cell['cell_id']}: winner reason requires winner side 0 or 1")
        return "win" if winner == int(cell["controlled_side"]) else "loss"
    if reason == "side_turn_cap":
        if winner is not None or turns != int(cell["max_side_turns"]):
            raise ValueError(f"{cell['cell_id']}: cap outcome has inconsistent winner or turn count")
        return "cap"
    if reason == "draw":
        if winner is not None:
            raise ValueError(f"{cell['cell_id']}: draw must not have a winner")
        return "draw"
    raise ValueError(f"{cell['cell_id']}: missing or unsupported termination reason")


def validate_mechanics_assertions(cell: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    """Evaluate the fixed mechanics assertion vocabulary from real result data."""
    for assertion in cell.get("assertions", []):
        kind = assertion.get("kind") if isinstance(assertion, dict) else None
        if kind == "terminal_winner":
            if result.get("termination_reason") != "winner":
                raise ValueError(f"{cell['cell_id']}: terminal_winner assertion failed")
            expected = assertion.get("winner_side")
            if expected is not None and result.get("winner_side") != expected:
                raise ValueError(f"{cell['cell_id']}: expected winner side {expected}")
        elif kind == "no_cap":
            if result.get("termination_reason") == "side_turn_cap":
                raise ValueError(f"{cell['cell_id']}: no_cap assertion failed")
        else:
            raise ValueError(f"{cell['cell_id']}: unsupported mechanics assertion {kind!r}")


def _load_trace(trace_dir: Path, cell: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    path = trace_dir / "game-00001.ndjson"
    if not path.is_file():
        raise ValueError(f"{cell['cell_id']}: missing recorded game trace")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(records) < 2 or records[0].get("type") != "metadata" or records[-1].get("type") != "terminal":
        raise ValueError(f"{cell['cell_id']}: malformed game trace boundaries")
    meta, terminal = records[0], records[-1]
    if meta.get("algorithms") != _expected_algorithms(cell):
        raise ValueError(f"{cell['cell_id']}: trace algorithm identity mismatch")
    trace_expected = {"input_seed": int(cell["seed"]),
                      "effective_seed": _mix_seed(int(cell["seed"])),
                      "scenario": cell["scenario"],
                      "factions": [cell["faction"], cell["faction"]],
                      "first": 0 if cell["first"] == "team1" else 1,
                      "starting_gold": [int(cell["gold"]), int(cell["gold"])],
                      "side_turn_cap": int(cell["max_side_turns"])}
    for key, value in trace_expected.items():
        if meta.get(key) != value:
            raise ValueError(f"{cell['cell_id']}: trace {key} mismatch")
    if meta.get("recruitment_policies") != [cell["recruit1_policy"], cell["recruit2_policy"]]:
        raise ValueError(f"{cell['cell_id']}: trace recruitment policy mismatch")
    expected_reason = "winner" if result["termination_reason"] == "winner" else "safety_cap"
    if terminal.get("reason") != expected_reason or terminal.get("winner") != result.get("winner_side"):
        raise ValueError(f"{cell['cell_id']}: trace terminal does not match result")
    if terminal.get("side_turns_executed") != result.get("completed_side_turns"):
        raise ValueError(f"{cell['cell_id']}: trace turn count does not match result")
    return str(path.relative_to(trace_dir.parent.parent.parent))


def _atomic_json(path: Path, value: Any) -> None:
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temp.open("w") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    os.replace(temp, path)


def _append_attempt(path: Path, value: Mapping[str, Any]) -> None:
    with _JOURNAL_LOCK:
        with path.open("a") as stream:
            stream.write(json.dumps(value, sort_keys=True) + "\n")
            stream.flush(); os.fsync(stream.fileno())


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _run_cell(cell: Mapping[str, Any], *, binary: Path, out_dir: Path,
              timeout_seconds: float, attempt: int, journal: Path) -> dict[str, Any]:
    started = time.time()
    prefix = f"{cell['cell_id']}/attempt-{attempt:03d}"
    log_dir = out_dir / "logs" / str(cell["cell_id"])
    log_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = out_dir / "evidence" / str(cell["cell_id"]) / f"attempt-{attempt:03d}"
    trace_dir.parent.mkdir(parents=True, exist_ok=True)
    command = command_for(cell, binary, trace_dir)
    stdout_path = log_dir / f"attempt-{attempt:03d}.stdout"
    stderr_path = log_dir / f"attempt-{attempt:03d}.stderr"
    _append_attempt(journal, {"event": "start", "cell_id": cell["cell_id"], "attempt": attempt,
                              "started_unix": started, "command": command})
    status, outcome, engine = "failed", None, None
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            status, exit_code = "timeout", None
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    stdout_text, stderr_text = stdout_path.read_text(errors="replace"), stderr_path.read_text(errors="replace")
    reason = None
    trace = None
    if status != "timeout" and exit_code == 0:
        rows = _result_lines(stdout_text)
        if len(rows) == 1:
            try:
                engine = rows[0]
                outcome = validate_engine_result(cell, engine)
                if "assertions" in cell:
                    validate_mechanics_assertions(cell, engine)
                trace = _load_trace(trace_dir, cell, engine)
                status = "completed"
            except (ValueError, json.JSONDecodeError) as error:
                reason = str(error)
        else:
            reason = f"expected one self_play_result row, found {len(rows)}"
    elif status != "timeout":
        reason = f"process exit {exit_code}"
    row = {**dict(cell), "status": status, "outcome": outcome, "exit_code": exit_code,
           "engine_result": engine, "trace": trace, "stdout": str(stdout_path.relative_to(out_dir)),
           "stderr": str(stderr_path.relative_to(out_dir)), "attempt": attempt,
           "command": command, "elapsed_seconds": round(time.time() - started, 3),
           "failure_reason": reason}
    _append_attempt(journal, {"event": "exit", "cell_id": cell["cell_id"], "attempt": attempt,
                              "ended_unix": time.time(), "status": status, "exit_code": exit_code,
                              "failure_reason": reason})
    return row


def _validate_cell_result(cell: Mapping[str, Any], row: Mapping[str, Any], out_dir: Path,
                          binary: Path | None = None) -> None:
    if row.get("cell_id") != cell["cell_id"]:
        raise ValueError(f"foreign or mismatched cell id {row.get('cell_id')!r}")
    status = row.get("status")
    if status not in ("completed", "failed", "timeout", "unrun"):
        raise ValueError(f"{cell['cell_id']}: malformed status")
    if status != "completed":
        if row.get("outcome") is not None:
            raise ValueError(f"{cell['cell_id']}: unresolved cell cannot claim an outcome")
        return
    engine = row.get("engine_result")
    if not isinstance(engine, dict):
        raise ValueError(f"{cell['cell_id']}: completed row lacks engine result")
    outcome = validate_engine_result(cell, engine)
    if "assertions" in cell:
        validate_mechanics_assertions(cell, engine)
    if row.get("outcome") != outcome:
        raise ValueError(f"{cell['cell_id']}: derived outcome mismatch")
    if binary is not None:
        attempt = row.get("attempt")
        if not isinstance(attempt, int) or attempt < 1:
            raise ValueError(f"{cell['cell_id']}: invalid attempt number")
        trace_dir = out_dir / "evidence" / str(cell["cell_id"]) / f"attempt-{attempt:03d}"
        if row.get("command") != command_for(cell, binary, trace_dir):
            raise ValueError(f"{cell['cell_id']}: launched argv differs from frozen cell contract")
    for field in ("stdout", "stderr", "trace"):
        ref = row.get(field)
        if not isinstance(ref, str) or not ref:
            raise ValueError(f"{cell['cell_id']}: missing {field} evidence reference")
        path = (out_dir / ref).resolve()
        if out_dir.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"{cell['cell_id']}: invalid {field} evidence path")
    trace_path = out_dir / row["trace"]
    records = [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]
    if records[-1].get("type") != "terminal":
        raise ValueError(f"{cell['cell_id']}: malformed trace terminal")


def aggregate_results(schedule: Iterable[Mapping[str, Any]], results: Iterable[Mapping[str, Any]],
                      *, suite: str = "screen") -> dict[str, Any]:
    scheduled = list(schedule)
    provided = list(results)
    by_id: dict[str, Mapping[str, Any]] = {}
    invalid = []
    expected_ids = {str(c["cell_id"]) for c in scheduled}
    for row in provided:
        cell_id = str(row.get("cell_id"))
        if cell_id not in expected_ids:
            invalid.append(f"foreign cell {cell_id}")
        elif cell_id in by_id:
            invalid.append(f"duplicate cell {cell_id}")
        else:
            by_id[cell_id] = row
    rows = []
    for cell in scheduled:
        row = dict(by_id.get(str(cell["cell_id"]), {"status": "unrun", "outcome": None}))
        row.setdefault("cell_id", cell["cell_id"])
        row.setdefault("opponent", cell.get("opponent", "mechanics"))
        row.setdefault("faction", cell.get("faction", "fixture"))
        row.setdefault("controlled_side", cell.get("controlled_side", 0))
        rows.append(row)

    def summarize(subset: list[Mapping[str, Any]]) -> dict[str, Any]:
        statuses = Counter(str(r.get("status")) for r in subset)
        outcomes = Counter(str(r.get("outcome")) for r in subset if r.get("status") == "completed")
        completed = statuses["completed"]
        wins, losses, caps, draws = outcomes["win"], outcomes["loss"], outcomes["cap"], outcomes["draw"]
        return {"scheduled": len(subset), "completed": completed,
                "wins": wins, "losses": losses, "genuine_draws": draws, "caps": caps,
                "invalid": statuses["invalid"], "timed_out": statuses["timeout"],
                "unrun": statuses["unrun"], "failed": statuses["failed"],
                "operational_failures": len(subset) - completed,
                "win_rate_all_scheduled": wins / len(subset) if subset else None,
                "win_rate_completed": wins / completed if completed else None,
                "status_counts": dict(statuses), "outcome_counts": dict(outcomes)}

    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row["opponent"]), []).append(row)
    summaries = {opponent: summarize(group) for opponent, group in sorted(groups.items())}
    all_summary = summarize(rows)
    complete = not invalid and all_summary["operational_failures"] == 0
    rate = all_summary["win_rate_all_scheduled"]
    strength_threshold = WIN_RATE_THRESHOLDS.get(suite)
    if suite == "smoke" or suite == "mechanics":
        strength = "not_measured"
    elif suite == "screen":
        strength = "measured_not_certifying"
    elif not complete:
        strength = "incomplete"
    else:
        by_opponent_pass = all(s["win_rate_all_scheduled"] >= strength_threshold for s in summaries.values())
        strength = "passed" if by_opponent_pass else "failed"
    return {"schema_version": SCHEMA_VERSION, "suite": suite, "rows": rows,
            "summary": summaries, "overall": all_summary, "status": "complete" if complete and not invalid else "incomplete",
            "invalid_records": invalid,
            "verdicts": {"implementation": "not_assessed", "gameplay": "passed" if complete else "incomplete",
                         "strength": strength},
            "strength_gate": {"threshold_per_opponent": strength_threshold,
                              "passed": strength == "passed",
                              "promotion_allowed": suite == "heldout" and strength == "passed"},
            "note": "Wins use all scheduled cells as denominator; caps, failures, timeouts, invalid, and unrun cells are not wins."}


def _manifest_payload(suite: str, schedule: list[dict[str, Any]], *, root: Path,
                      binary: Path, timeout: float, workers: int, base_seed: int,
                      gold: int, cap: int, mechanics_manifest: Path | None) -> dict[str, Any]:
    source = source_identity(root)
    if not binary.is_file():
        raise ValueError(f"self-play binary does not exist: {binary}")
    return {"schema_version": SCHEMA_VERSION, "suite": suite, "status": "frozen",
            "source": source, "binary": str(binary.resolve()), "binary_sha256": sha256_file(binary),
            "data_sha256": data_sha256(root), "timeout_seconds": timeout, "workers": workers,
            "schedule": schedule, "schedule_sha256": hashlib.sha256(_canonical_bytes(schedule)).hexdigest(),
            "settings": {"base_seed": base_seed, "gold": gold, "max_side_turns": cap,
                         "second_gold": 0, "threads": 1,
                         "controlled_algorithm": CONTROLLED_ALGORITHM},
            "mechanics_manifest": str(mechanics_manifest.resolve()) if mechanics_manifest else None}


def _mix_seed(value: int) -> int:
    mask = (1 << 64) - 1
    value = (value + 0x9e3779b97f4a7c15) & mask
    value = ((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9) & mask
    value = ((value ^ (value >> 27)) * 0x94d049bb133111eb) & mask
    value ^= value >> 31
    return value or 1


def _load_manifest(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "manifest.json"
    if not path.is_file():
        raise ValueError("missing frozen manifest")
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != "frozen":
        raise ValueError("unsupported or non-frozen manifest")
    schedule = manifest.get("schedule")
    if not isinstance(schedule, list) or manifest.get("schedule_sha256") != hashlib.sha256(_canonical_bytes(schedule)).hexdigest():
        raise ValueError("manifest schedule hash mismatch")
    if manifest.get("settings", {}).get("controlled_algorithm") != CONTROLLED_ALGORITHM:
        raise ValueError("manifest controlled algorithm is not coordinated")
    settings = manifest["settings"]
    mechanics_manifest = Path(manifest["mechanics_manifest"]) if manifest.get("mechanics_manifest") else None
    expected = build_schedule(suite=manifest["suite"], base_seed=settings["base_seed"],
                              gold=settings["gold"], max_side_turns=settings["max_side_turns"],
                              mechanics_manifest=mechanics_manifest,
                              through_stack=settings.get("through_stack", 7))
    if schedule != expected:
        raise ValueError("manifest cells do not match the official suite contract")
    return manifest


def check_evidence(out_dir: Path) -> tuple[int, dict[str, Any]]:
    """Validate a run directory without invoking the game process."""
    try:
        manifest = _load_manifest(out_dir)
        source = manifest.get("source", {})
        if source_identity(ROOT) != source:
            raise ValueError("source commit/tree differs from frozen manifest")
        binary = Path(manifest["binary"])
        if not binary.is_file() or sha256_file(binary) != manifest.get("binary_sha256"):
            raise ValueError("binary missing or hash differs from frozen manifest")
        if data_sha256(ROOT) != manifest.get("data_sha256"):
            raise ValueError("game data hash differs from frozen manifest")
        results_path = out_dir / "results.json"
        if not results_path.is_file():
            raise ValueError("missing results.json")
        decoded = json.loads(results_path.read_text())
        results = decoded.get("results")
        if not isinstance(results, list):
            raise ValueError("results.json lacks a results array")
        errors = []
        by_id = {}
        schedule_ids = {cell["cell_id"] for cell in manifest["schedule"]}
        for row in results:
            if not isinstance(row, dict):
                errors.append("malformed result row"); continue
            cid = row.get("cell_id")
            if cid not in schedule_ids:
                errors.append(f"foreign cell {cid}"); continue
            if cid in by_id:
                errors.append(f"duplicate cell {cid}"); continue
            by_id[cid] = row
            cell = next(c for c in manifest["schedule"] if c["cell_id"] == cid)
            try:
                _validate_cell_result(cell, row, out_dir, binary)
            except (ValueError, OSError, json.JSONDecodeError) as error:
                errors.append(str(error))
        for cell in manifest["schedule"]:
            row = by_id.get(cell["cell_id"])
            if row is None:
                errors.append(f"unrun cell {cell['cell_id']}")
        journal_path = out_dir / "attempts.jsonl"
        starts: Counter[tuple[str, int]] = Counter()
        exits: Counter[tuple[str, int]] = Counter()
        if not journal_path.is_file():
            errors.append("missing attempt journal")
        else:
            for line_number, line in enumerate(journal_path.read_text().splitlines(), 1):
                try:
                    event = json.loads(line)
                    key = (event["cell_id"], int(event["attempt"]))
                    if key[0] not in schedule_ids or event.get("event") not in ("start", "exit"):
                        raise ValueError("foreign attempt event")
                    (starts if event["event"] == "start" else exits)[key] += 1
                except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                    errors.append(f"malformed attempt journal line {line_number}")
            for key in set(starts) | set(exits):
                if starts[key] != 1 or exits[key] != 1:
                    errors.append(f"unmatched or duplicate attempt event for {key[0]} attempt {key[1]}")
            for cid in by_id:
                if not any(k[0] == cid and starts[k] == exits[k] == 1 for k in starts):
                    errors.append(f"missing matched attempt start/exit for {cid}")
        report = aggregate_results(manifest["schedule"], results, suite=manifest["suite"])
        report["invalid_records"].extend(errors)
        complete = not errors and report["status"] == "complete"
        report["status"] = "complete" if complete else "incomplete"
        report["verdicts"]["gameplay"] = "passed" if complete else "incomplete"
        if errors:
            report["verdicts"]["strength"] = "incomplete"
        threshold = report["strength_gate"]["threshold_per_opponent"]
        if complete and threshold is not None:
            passed = all(v["win_rate_all_scheduled"] >= threshold for v in report["summary"].values())
            report["verdicts"]["strength"] = "passed" if passed else "failed"
            report["strength_gate"]["passed"] = passed
            report["strength_gate"]["promotion_allowed"] = manifest["suite"] == "heldout" and passed
        report["verdicts"]["implementation"] = "passed" if not errors else "failed"
        code = 2 if errors or not complete else 1 if report["verdicts"]["strength"] == "failed" else 0
        return code, report
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        return 2, {"status": "invalid", "invalid_records": [str(error)],
                   "verdicts": {"implementation": "failed", "gameplay": "incomplete", "strength": "incomplete"},
                   "strength_gate": {"passed": False, "promotion_allowed": False}}


def run_suite(*, suite: str, out_dir: Path, binary: Path, base_seed: int,
              gold: int, max_side_turns: int, timeout_seconds: float, workers: int,
              resume: bool, mechanics_manifest: Path | None = None,
              through_stack: int = 7) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = binary.resolve()
    schedule = build_schedule(suite=suite, base_seed=base_seed, gold=gold,
                              max_side_turns=max_side_turns,
                              mechanics_manifest=mechanics_manifest,
                              through_stack=through_stack)
    if suite == "mechanics":
        if mechanics_manifest is None or not mechanics_manifest.is_file():
            raise ValueError("mechanics suite requires the tracked Stack 1 fixture manifest")
    manifest_path, results_path = out_dir / "manifest.json", out_dir / "results.json"
    if resume:
        manifest = _load_manifest(out_dir)
        candidate = _manifest_payload(suite, schedule, root=ROOT, binary=binary,
                                      timeout=timeout_seconds, workers=workers, base_seed=base_seed,
                                      gold=gold, cap=max_side_turns, mechanics_manifest=mechanics_manifest)
        candidate["settings"]["through_stack"] = through_stack
        for key in ("suite", "source", "binary", "binary_sha256", "data_sha256", "schedule_sha256",
                    "settings", "timeout_seconds", "workers"):
            if manifest.get(key) != candidate.get(key):
                raise ValueError(f"resume refused: frozen manifest {key} mismatch")
    else:
        if manifest_path.exists() or results_path.exists():
            raise ValueError("output directory already contains a run; use --resume or choose a new directory")
        manifest = _manifest_payload(suite, schedule, root=ROOT, binary=binary,
                                     timeout=timeout_seconds, workers=workers, base_seed=base_seed,
                                     gold=gold, cap=max_side_turns, mechanics_manifest=mechanics_manifest)
        manifest["settings"]["through_stack"] = through_stack
        _atomic_json(manifest_path, manifest)
        _atomic_json(results_path, {"results": []})
    existing = json.loads(results_path.read_text()).get("results", []) if results_path.exists() else []
    by_id = {}
    attempt_by_id = {}
    for row in existing:
        cell = next((c for c in schedule if c["cell_id"] == row.get("cell_id")), None)
        if cell is None or row["cell_id"] in by_id:
            raise ValueError("resume refused: existing results have foreign or duplicate cells")
        if row.get("status") == "completed":
            _validate_cell_result(cell, row, out_dir, binary)
        elif row.get("status") not in ("failed", "timeout"):
            raise ValueError("resume refused: malformed existing result")
        by_id[row["cell_id"]] = row
        attempt_by_id[row["cell_id"]] = int(row.get("attempt", 0))
    journal = out_dir / "attempts.jsonl"
    # Close attempts interrupted between the durable start and exit records.
    if resume and journal.is_file():
        events = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
        starts = {(e["cell_id"], int(e["attempt"])) for e in events if e.get("event") == "start"}
        exits = {(e["cell_id"], int(e["attempt"])) for e in events if e.get("event") == "exit"}
        for cid, attempt in starts:
            attempt_by_id[cid] = max(attempt_by_id.get(cid, 0), attempt)
        for cid, attempt in sorted(starts - exits):
            _append_attempt(journal, {"event": "exit", "cell_id": cid, "attempt": attempt,
                                      "ended_unix": time.time(), "status": "interrupted",
                                      "exit_code": None, "failure_reason": "recovered by --resume"})
    pending = [c for c in schedule if by_id.get(c["cell_id"], {}).get("status") != "completed"]
    if workers < 1 or workers > 3:
        raise ValueError("workers must be between 1 and 3")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_run_cell, c, binary=binary, out_dir=out_dir,
                               timeout_seconds=timeout_seconds,
                               attempt=attempt_by_id.get(c["cell_id"], 0) + 1, journal=journal): c
                   for c in pending}
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            by_id[row["cell_id"]] = row
            _atomic_json(results_path, {"results": [by_id[c["cell_id"]] for c in schedule if c["cell_id"] in by_id]})
    report = aggregate_results(schedule, [by_id[c["cell_id"]] for c in schedule if c["cell_id"] in by_id], suite=suite)
    _atomic_json(out_dir / "report.json", report)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="algorithm_strength")
    parser.add_argument("--binary", type=Path, default=ROOT / "norrust_core/target/release/self-play")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--suite", choices=("smoke", "screen", "development", "heldout", "mechanics"), default="screen")
    parser.add_argument("--base-seed", type=int, default=26001)
    parser.add_argument("--gold", type=int, default=300)
    parser.add_argument("--max-side-turns", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--through-stack", type=int, default=7)
    parser.add_argument("--mechanics-manifest", type=Path)
    args = parser.parse_args(argv)
    if args.max_side_turns < 1 or args.timeout_seconds <= 0 or args.gold < 1:
        parser.error("gold, timeout, and caps must be positive")
    if args.suite == "mechanics" and not 0 <= args.through_stack <= 7:
        parser.error("--through-stack must be between 0 and 7")
    if args.check:
        code, report = check_evidence(args.out_dir)
        print(json.dumps(report, sort_keys=True))
        return code
    if not args.binary.is_file():
        parser.error(f"self-play binary does not exist: {args.binary}")
    try:
        run_suite(suite=args.suite, out_dir=args.out_dir, binary=args.binary,
                  base_seed=args.base_seed, gold=args.gold, max_side_turns=args.max_side_turns,
                  timeout_seconds=args.timeout_seconds, workers=args.workers, resume=args.resume,
                  mechanics_manifest=args.mechanics_manifest,
                  through_stack=args.through_stack)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "invalid", "error": str(error),
                          "verdicts": {"implementation": "failed", "gameplay": "incomplete", "strength": "incomplete"}}), file=sys.stderr)
        return 2
    code, report = check_evidence(args.out_dir)
    _atomic_json(args.out_dir / "report.json", report)
    print(json.dumps({"status": report["status"], "suite": args.suite,
                      "verdicts": report["verdicts"], "summary": report["overall"]}, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
