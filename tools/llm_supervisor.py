#!/usr/bin/env python3
"""Run llm_client with bounded recovery from process/infrastructure failure."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from .luna_reconcile import reconcile_request
except ImportError:  # Direct ``python tools/llm_supervisor.py`` invocation.
    from luna_reconcile import reconcile_request


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _has_checkpoint(log: Path) -> bool:
    directory = log.with_suffix(".ckpt")
    return any(path.is_file() and path.suffix == ".json" for path in directory.glob("*.json"))


def _last_terminal(log: Path) -> dict | None:
    records = _records(log)
    terminal = next((record for record in reversed(records)
                     if record.get("type") == "terminal"), None)
    if terminal is not None:
        return terminal
    # Older client failure paths durably wrote model_error without a separate
    # terminal record. Treat only the latest such record as terminal evidence;
    # ordinary model/driver records must never trigger a resume.
    failure = next((record for record in reversed(records)
                    if record.get("type") in {"model_error", "checkpoint_error"}), None)
    if failure is None:
        return None
    return {"terminal_class": failure.get("terminal_class") or
            ("infrastructure" if failure.get("type") == "checkpoint_error" else None),
            "type": "derived_terminal", "source_type": failure.get("type")}


def _append(log: Path, value: dict) -> None:
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(command: list[str], log: Path, max_restarts: int,
        request_state: Path | None = None) -> int:
    restarts = 0
    while True:
        invocation = command if restarts == 0 else command + ["--resume-log", str(log)]
        completed = subprocess.run(invocation)
        terminal = _last_terminal(log)
        terminal_class = terminal.get("terminal_class") if terminal else None
        recoverable = completed.returncode < 0 or terminal_class == "infrastructure"
        if recoverable and request_state is not None:
            try:
                reconciliation = reconcile_request(
                    request_state, log, checkpoint_dir=log.with_suffix(".ckpt"))
            except (OSError, ValueError) as exc:
                _append(log, {"type": "supervisor_reconciliation", "state": "unknown",
                              "safe_to_restart": False,
                              "reason": f"reconciliation error: {exc}", "request_id": None})
                recoverable = False
            else:
                _append(log, {"type": "supervisor_reconciliation",
                              "state": reconciliation.state,
                              "safe_to_restart": reconciliation.safe_to_restart,
                              "reason": reconciliation.reason,
                              "request_id": reconciliation.request_id})
                recoverable = reconciliation.safe_to_restart
        if not recoverable or restarts >= max_restarts or not _has_checkpoint(log):
            return completed.returncode
        restarts += 1
        _append(log, {"type": "supervisor_attempt", "attempt": restarts,
                      "previous_returncode": completed.returncode,
                      "reason": "signal" if completed.returncode < 0 else "infrastructure"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--request-state", type=Path,
                        help="durable Luna request state used to authorize recovery")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="client command after --")
    args = parser.parse_args(argv)
    if args.max_restarts < 0:
        parser.error("--max-restarts must be non-negative")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a client command is required after --")
    if "--log" not in command:
        parser.error("the client command must include --log")
    return run(command, args.log, args.max_restarts, args.request_state)


if __name__ == "__main__":
    raise SystemExit(main())
