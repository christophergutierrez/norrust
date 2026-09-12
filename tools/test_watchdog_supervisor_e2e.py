import hashlib
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .game_history import import_game, open_history, query_usage
from .llm_supervisor import run
from .run_watchdog import RunWatchdog
from .watchdog_observer import FakeObserverBackend
from .watchdog_stop import read_stop


class WatchdogSupervisorE2ETests(unittest.TestCase):
    def test_real_client_stream_and_observer_stop_import_twice(self):
        driver = Path(os.environ.get(
            "NORRUST_TEST_DRIVER", "norrust_core/target/debug/greedy_driver")).resolve()
        if not driver.is_file():
            self.skipTest("build greedy_driver or run tools.fast_check")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            # The supervisor's short polling loop must receive distinct
            # recorder sequences so repeated evidence counts as two fresh
            # observations before the investigation stop.
            recorder = RunWatchdog(log, poll_interval=0)
            observer_calls = []
            clock_state = {"alert_seen": False, "ticks": 0}

            def observe_fixture(payload):
                packet = json.loads(payload["input"])["watchdog_packet"]
                alerts = packet.get("alerts", [])
                if not alerts:
                    return {"decision": "continue", "reason_code": "healthy",
                            "evidence_ids": [], "explanation": "fixture"}
                observer_calls.append(packet["observation_sequence"])
                clock_state["alert_seen"] = True
                if len(observer_calls) == 1:
                    # Leave the real provider stream open while the recorder
                    # emits another status sequence; the stop fence needs two
                    # fresh observations of this one incident.
                    import time
                    time.sleep(0.3)
                evidence = packet.get("evidence_ids", [])[:1]
                # One alert observation is allowed to continue, the next
                # launches the required inspection, and its automatic
                # investigation returns the validated stop. The max of three
                # physical calls is the entire fixture budget.
                kind = ("continue" if len(observer_calls) == 1 else
                        "inspect" if len(observer_calls) == 2 else "stop")
                return {"decision": kind,
                        "reason_code": ("healthy" if kind == "continue" else
                                         "check" if kind == "inspect" else
                                         "repeated_no_progress"),
                        "evidence_ids": evidence, "explanation": "fixture"}

            def clock():
                if not clock_state["alert_seen"]:
                    return 0.0
                clock_state["ticks"] += 300
                return clock_state["ticks"]

            backend = FakeObserverBackend(observe_fixture)
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(driver),
                       "--log", str(log), "--max-turns", "2", "--model-command",
                       shlex.join([sys.executable, "-m",
                                   "tools.fixtures.watchdog_stream_player"])]
            with mock.patch.dict(os.environ, {
                    "NORRUST_WATCHDOG_REPEAT_REASONING": "1",
            }, clear=False):
                result = run(command, log, 0, watchdog=recorder, poll_interval=.01,
                             watchdog_mode="enforce", observer_backend=backend,
                             observer_clock=clock, observer_max_calls=3)
            self.assertEqual(result, 4)
            self.assertEqual(len(observer_calls), 3)
            intent = read_stop(log)
            self.assertEqual(intent["status"], "resolved")
            self.assertEqual(intent["resolution"], "cancelled")
            summary = json.loads((recorder.run_directory / "review.json").read_text())
            self.assertEqual(summary["game_result"]["terminal_class"], "observer_interrupted")
            self.assertIsNone(summary["game_result"]["winner"])
            self.assertEqual(summary["model_evaluation"]["status"], "offline_fake")
            self.assertEqual(recorder.status()["usage_coverage"]["call_count"], 1)
            packets = [json.loads(line)["status"]
                       for line in recorder.journal_path.read_text().splitlines()
                       if json.loads(line).get("type") == "status"]
            live = [packet for packet in packets
                    if packet.get("current_request")
                    and packet["received_stream_bytes"] > 0]
            self.assertTrue(live, "the repeated provider stream must be observed live")
            self.assertTrue(any(packet.get("alerts") for packet in live))

            usage = root / "usage.ndjson"
            rows = [json.loads(line) for line in usage.read_text().splitlines()]
            self.assertTrue(any(row.get("call_role") == "player" for row in rows))
            self.assertTrue(any(row.get("call_role") == "observer" for row in rows))
            metadata = next(row for row in (json.loads(line) for line in log.read_text().splitlines())
                            if row.get("type") == "metadata")
            catalog_id = metadata["conversation_id"]
            self.assertEqual(summary["source"]["conversation_id"], catalog_id)
            from .watchdog_review import review
            self.assertEqual(review(log)["usage"]["observer"]["calls"], 3)
            evidence = next(recorder.evidence_dir.glob("*/prompt.txt"))
            context = json.loads((evidence.parent / "request_context.json").read_text())
            self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(),
                             context["prompt_sha256"])
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, log, game_id=catalog_id)
            first = query_usage(conn, game_id, "game")
            import_game(conn, log, game_id=catalog_id)
            second = query_usage(conn, game_id, "game")
            self.assertEqual(first["role_usage"]["observer"]["call_count"],
                             second["role_usage"]["observer"]["call_count"])
            self.assertGreater(first["role_usage"]["player"]["call_count"], 0)
            self.assertGreater(first["role_usage"]["observer"]["call_count"], 0)
            self.assertIsNone(conn.execute(
                "SELECT winner_side FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            conn.close()


if __name__ == "__main__":
    unittest.main()
