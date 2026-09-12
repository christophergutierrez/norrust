import json
import tempfile
import time
import unittest
from pathlib import Path

from .game_history import import_game, open_history, query_usage
from .watchdog_integration import (WatchdogIdentityError, attach_observer,
                                   prove_catalog_identity)
from .watchdog_observer import FakeObserverBackend


def _decision(kind, reason, ids=()):
    return {"decision": kind, "reason_code": reason,
            "evidence_ids": list(ids), "explanation": "offline fixture"}


class IdentityIntegrationTests(unittest.TestCase):
    def test_run_uuid_never_proves_catalog_identity(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            with self.assertRaises(WatchdogIdentityError):
                prove_catalog_identity(log, explicit="fresh-run-uuid")

    def test_context_identity_must_agree_with_explicit_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            (root / "request_context.json").write_text(
                json.dumps({"conversation_id": "catalog-game"}))
            self.assertEqual(prove_catalog_identity(log), "catalog-game")
            with self.assertRaises(WatchdogIdentityError):
                prove_catalog_identity(log, explicit="different-game")


try:
    from .run_watchdog import RunWatchdog
except ImportError:  # Stack 1 is merged by the parent branch.
    RunWatchdog = None


@unittest.skipIf(RunWatchdog is None, "RunWatchdog is supplied by the progress stack")
class RealRunWatchdogIntegrationTests(unittest.TestCase):
    def test_real_packet_sidecar_import_and_repeated_inspection_stop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "match.ndjson"
            metadata = {"type": "metadata", "conversation_id": "catalog-game",
                        "llm_side": 0}
            request = {"type": "model_request", "request_id": "catalog-game:request:1",
                       "status": "started", "state_revision": 1}
            log.write_text("\n".join(json.dumps(row) for row in (metadata, request)) + "\n")
            context = root / "request_context.json"
            context.write_text(json.dumps({"conversation_id": "catalog-game"}))
            watchdog = RunWatchdog(log, run_id="fresh-run-uuid", evidence_dir=root / "evidence",
                                   poll_interval=0, regular_interval=300, cooldown=60)
            packet = watchdog.poll(force=True)
            self.assertEqual(packet["stage"], "request")
            self.assertEqual(packet["run_id"], "fresh-run-uuid")
            backend = FakeObserverBackend([
                _decision("inspect", "check", packet["evidence_ids"][:1]),
                _decision("stop", "repeated_no_progress", packet["evidence_ids"][:1]),
                _decision("inspect", "check", packet["evidence_ids"][:1]),
                _decision("stop", "repeated_no_progress", packet["evidence_ids"][:1]),
            ])
            stops = []
            now = [0.0]
            controller = attach_observer(
                watchdog, log, backend=backend, mode="enforce",
                stop=lambda *args: stops.append(args), usage_sidecar=root / "usage.ndjson",
                clock=lambda: now[0])
            # Feed the actual recorder packet through the real controller. Its
            # status is retained as the current progress source while this
            # test advances the two observation generations.
            # This fixture has no malformed recorder input; clear only the
            # source's local startup warning so the stop gate can exercise
            # the actual packet shape.
            current = [dict(packet, degraded=False, coverage_events=[],
                            alerts=[{"identity": "incident", "revision": packet.get("revision")}])]
            controller.progress = lambda _run: current[0]
            self.assertTrue(controller.poll(current[0]))
            controller.wait(2)
            current[0] = dict(current[0], observation_sequence=packet["observation_sequence"] + 1)
            # Regular cadence is the only reason to inspect an unchanged alert.
            current[0]["revision"] = packet.get("revision")
            current[0]["alerts"] = [{"identity": "incident", "revision": packet.get("revision")}]
            # Move the controller's injected monotonic source by replacing it
            # with a deterministic clock for this offline replay.
            now[0] = 300.0
            self.assertTrue(controller.poll(current[0]))
            controller.wait(2)
            for _ in range(100):
                if not controller.active:
                    break
                time.sleep(.005)
            self.assertEqual(len(stops), 1)
            controller.close(wait=True)

            log.write_text(log.read_text() + json.dumps({"type": "terminal", "reason": "watchdog_stop"}) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, log, game_id="catalog-game")
            report = query_usage(conn, game_id, "game")
            self.assertEqual(report["role_usage"]["observer"]["call_count"], 4)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id=? AND call_role='observer'",
                (game_id,)).fetchone()[0], 4)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id=? AND game_id='fresh-run-uuid'",
                (game_id,)).fetchone()[0], 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
