#!/usr/bin/env python3
"""Provider-neutral client for the greedy_driver JSON-lines protocol."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

ACTIONS = {"Move", "Attack", "Recruit", "RecruitBatch", "EndTurn", "Advance"}


@dataclass
class ModelReply:
    text: str
    usage: Optional[dict[str, int]] = None


class ModelBackend:
    def complete(self, prompt: str) -> ModelReply:
        raise NotImplementedError


class OrdersBackend(ModelBackend):
    def __init__(self, path: str):
        self.lines = iter(Path(path).read_text().splitlines())

    def complete(self, prompt: str) -> ModelReply:
        try:
            obj = json.loads(next(self.lines))
        except (StopIteration, json.JSONDecodeError) as exc:
            raise RuntimeError("model_error: invalid or exhausted orders file") from exc
        if not isinstance(obj, dict) or not isinstance(obj.get("text"), str):
            raise RuntimeError("model_error: orders line must be a ModelReply object")
        return ModelReply(obj["text"], obj.get("usage"))


class CommandBackend(ModelBackend):
    def __init__(self, command: str, timeout: float):
        self.command, self.timeout = command, timeout

    def complete(self, prompt: str) -> ModelReply:
        try:
            proc = subprocess.run(self.command, input=prompt, text=True, shell=True,
                                  capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("model_timeout") from exc
        if proc.returncode:
            raise RuntimeError(f"model_error: exit {proc.returncode}: {proc.stderr[-400:]}")
        try:
            obj = json.loads(proc.stdout)
            return ModelReply(obj["text"], obj.get("usage"))
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("model_error: invalid JSON reply") from exc


def validate_orders(text: str, strict: bool = False) -> list[dict[str, Any]]:
    try:
        orders = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(orders, list) or not orders or len(orders) > 256:
        raise ValueError("orders must be a non-empty array of at most 256 objects")
    end_indices = []
    for i, order in enumerate(orders):
        if not isinstance(order, dict) or order.get("action") not in ACTIONS:
            raise ValueError(f"invalid action at index {i}")
        if order["action"] == "Query":
            raise ValueError("Query is not a model action")
        if strict and order["action"] == "RecruitBatch":
            raise ValueError("RecruitBatch is disabled in strict mode")
        end_indices += [i] if order["action"] == "EndTurn" else []
    if len(end_indices) != 1 or end_indices[0] != len(orders) - 1:
        raise ValueError("exactly one final EndTurn is required")
    return orders


def prompt_for(state: dict[str, Any], events: list[dict[str, Any]]) -> str:
    rules = ("You play Norrust. Choose legal tactical actions from the supplied board. "
             "Return only a JSON array of actions, ending with EndTurn. "
             "Move, Attack, Recruit, Advance, and EndTurn are available.")
    return rules + "\nBOARD:\n" + json.dumps(state, sort_keys=True, separators=(",", ":")) + \
        "\nEVENTS:\n" + json.dumps(events, sort_keys=True, separators=(",", ":"))


def run(args: argparse.Namespace) -> int:
    driver = args.driver
    cmd = [driver, "--scenario", args.scenario, "--faction0", args.faction0,
           "--faction1", args.faction1, "--gold", str(args.gold), "--seed", str(args.seed),
           "--max-turns", str(args.max_turns), "--llm-side", str(args.llm_side)]
    if args.no_recruit_macro:
        cmd.append("--disable-recruit-batch")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    backend: ModelBackend = OrdersBackend(args.orders_file) if args.orders_file else CommandBackend(args.model_command, args.model_timeout)
    events: list[dict[str, Any]] = []
    state: Optional[dict[str, Any]] = None
    metadata = {"scenario": args.scenario, "faction0": args.faction0, "faction1": args.faction1,
                "gold": args.gold, "seed": args.seed, "llm_side": args.llm_side,
                "model_backend": "orders-file" if args.orders_file else "model-command",
                "llm_recruit_macro": not args.no_recruit_macro,
                "opponent": "greedy+driver-recruit", "opponent_recruit_policy": "standard_driver_macro",
                "opponent_planner": "no_skirmisher_pathing", "turn_format": "single_batch",
                "win_rule": "elimination_only", "queries": 0, "model_orders": 0, "model_calls": 0}
    log = open(args.log, "a", buffering=1) if args.log else None
    def record(obj: dict[str, Any]) -> None:
        if log:
            log.write(json.dumps(obj, sort_keys=True) + "\n")
            log.flush()
    record({"type": "metadata", **metadata})
    try:
        while True:
            raw = proc.stdout.readline()
            if not raw:
                record({"type": "driver_crash", "returncode": proc.poll()})
                return 1
            line = json.loads(raw)
            record({"type": "driver", "line": line})
            if line.get("type") == "state":
                state = line
                # Ask the engine for the complete legal action surface before
                # the model call; legality is never reconstructed in Python.
                proc.stdin.write(json.dumps({"action": "Query", "what": "turn_options"}) + "\n")
                proc.stdin.flush()
                query_raw = proc.stdout.readline()
                if not query_raw:
                    record({"type": "driver_crash", "returncode": proc.poll()})
                    return 1
                query_line = json.loads(query_raw)
                metadata["queries"] += 1
                record({"type": "query", "line": query_line})
                if query_line.get("ok") and query_line.get("body"):
                    state = dict(state)
                    state["turn_options"] = query_line["body"]
                prompt = prompt_for(state, events)
                metadata["model_calls"] += 1
                try:
                    reply = backend.complete(prompt)
                    orders = validate_orders(reply.text, args.no_recruit_macro)
                except (RuntimeError, ValueError) as first:
                    record({"type": "model_error", "message": str(first)})
                    return 1
                metadata["model_orders"] += len(orders)
                proc.stdin.write(json.dumps(orders, separators=(",", ":")) + "\n")
                proc.stdin.flush()
            elif line.get("type") == "events":
                events.extend(line.get("events", []))
            elif line.get("type") == "game_end":
                metadata.update({"winner": line.get("winner"), "reason": line.get("reason")})
                record({"type": "terminal", **metadata})
                return 0
    finally:
        if log:
            log.close()
        if proc.poll() is None:
            proc.terminate()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--driver", default="norrust_core/target/debug/greedy_driver")
    p.add_argument("--scenario", default="big_battle_6")
    p.add_argument("--faction0", default="undead")
    p.add_argument("--faction1", default="undead")
    p.add_argument("--gold", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--llm-side", type=int, default=0)
    p.add_argument("--max-turns", type=int, default=200)
    p.add_argument("--orders-file")
    p.add_argument("--model-command")
    p.add_argument("--model-timeout", type=float, default=300)
    p.add_argument("--no-recruit-macro", action="store_true")
    p.add_argument("--log")
    a = p.parse_args()
    if bool(a.orders_file) == bool(a.model_command):
        p.error("choose exactly one of --orders-file or --model-command")
    return run(a)


if __name__ == "__main__":
    raise SystemExit(main())
