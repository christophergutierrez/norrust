"""Focused final-only strategy boundaries against the real driver."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import textwrap
import tempfile
import unittest

from .test_strategy_routine_stack2 import (
    DRIVER, engine_events, launch as launch_quiet, prepare as prepare_quiet,
    records,
)
from .test_strategy_routine_stack3 import (
    launch as launch_stack3, policy, prepare as prepare_stack3, prompts,
    forwarded,
)


@unittest.skipUnless(DRIVER.is_file(), "Build the actual integration driver; skipped is not acceptance")
class FinalOnlyStrategyTests(unittest.TestCase):
    def _query_revision_proxy(self, root: Path, what: str, *, missing: bool) -> Path:
        proxy = root / ("driver-" + what + ".py")
        proxy.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(f"""
            import json, subprocess, sys, threading
            child = subprocess.Popen([{str(DRIVER)!r}] + sys.argv[1:], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            def forward_input():
                for line in sys.stdin:
                    child.stdin.write(line)
                    child.stdin.flush()
            threading.Thread(target=forward_input, daemon=True).start()
            for raw in child.stdout:
                row = json.loads(raw)
                if row.get('what') == {what!r} and row.get('ok'):
                    if {missing!r}:
                        row.pop('state_revision', None)
                    else:
                        row['state_revision'] = -1
                print(json.dumps(row, separators=(',', ':')), flush=True)
        """).lstrip(), encoding="utf-8")
        proxy.chmod(0o755)
        return proxy

    def test_quiet_final_only_fixed_policy_uses_no_model_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy_file, backend, prompt_log = prepare_quiet(root)
            data = json.loads(checkpoint.read_text())
            data["accepted_partial_batches"] = 3
            data["max_partial_batches_per_turn"] = 3
            encoded = json.dumps(data, separators=(",", ":")).encode()
            checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
            checkpoint.write_bytes(encoded)
            log = root / "quiet-final-only.ndjson"
            result = launch_quiet(root, log, checkpoint, policy_file, backend,
                                  fixed=True, turns=1)
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text()[-8000:])
            rows = records(log)
            self.assertFalse(prompt_log.exists())
            self.assertFalse(any(row.get("type") == "model_request" for row in rows))
            self.assertTrue(any(order.get("action") == "FinishWithGreedy"
                                for row in rows if row.get("type") == "forwarded_orders"
                                for order in row.get("orders", [])))

    def test_final_only_promotion_is_rust_exception_then_model_finish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare_stack3(
                root, "promotion.json", [policy(), {"kind": "finish_turn"}],
                accepted=3, maximum=3)
            data = json.loads(checkpoint.read_text())
            # This archived position predates incremental mode; final-only
            # strategy execution requires the maintained partial-turn wire.
            data["incremental_turns"] = True
            data["max_partial_batches_per_turn"] = 3
            encoded = json.dumps(data, separators=(",", ":")).encode()
            checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
            checkpoint.write_bytes(encoded)
            log = root / "promotion-final-only.ndjson"
            result = launch_stack3(root, log, checkpoint, backend, maximum=3)
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text()[-8000:])
            rows = records(log)
            self.assertEqual(len(prompts(prompt_log)), 2)
            self.assertTrue(any(row.get("type") == "routine_exception"
                                and row.get("reason") == "promotion_pending" for row in rows))
            model_batches = [row for row in forwarded(rows) if row.get("source") == "llm"]
            self.assertTrue(any(any(order.get("action") == "FinishWithGreedy"
                                    for order in row.get("orders", []))
                                for row in model_batches))
            self.assertFalse(any(event.get("kind") == "advance" and event.get("source") == "llm"
                                 for event in engine_events(rows)))

    def test_missing_or_stale_strategy_query_revision_stops_before_action(self):
        for what, missing in (("recruit_options", True),
                              ("tactical_surface", False),
                              ("routine_next", False)):
            with self.subTest(what=what, missing=missing), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                checkpoint, _, backend, _ = prepare_stack3(
                    root, "contact.json", [policy(), {"kind": "finish_turn"}],
                    accepted=3, maximum=3)
                proxy = self._query_revision_proxy(root, what, missing=missing)
                log = root / (what + ".ndjson")
                result = launch_stack3(root, log, checkpoint, backend,
                                       maximum=3, driver_path=proxy)
                self.assertNotEqual(result.returncode, 0)
                rows = records(log)
                failure = [row for row in rows if row.get("type") == "query_error"][-1]
                self.assertIn("revision", failure.get("message", "").lower())
                self.assertFalse(any(row.get("type") == "forwarded_orders" for row in rows))
