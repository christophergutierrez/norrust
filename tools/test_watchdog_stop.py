import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from .llm_supervisor import _watchdog_validation, terminate_process_tree
from .run_watchdog import RunWatchdog
from .watchdog_stop import (StopError, read_stop, resolve_stop, stop_path_for_log,
                            stop_run, validate_stop_request)


class WatchdogStopTests(unittest.TestCase):
    def test_evidence_stop_is_stale_after_progress_advances(self):
        """A retained recent reference cannot authorize an old incident."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "run.ndjson"
            recorder = RunWatchdog(log, run_id="run-uuid", poll_interval=0)
            with log.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "forwarded_orders", "batch_id": "b1",
                                         "state_revision": 2}) + "\n")
            first = recorder.poll(force=True)
            evidence_id = first["recent_actions"][0]["evidence_id"]
            observed = first["observation_sequence"]
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "batch_committed", "batch_id": "b2",
                                         "state_revision": 3}) + "\n")
            current = recorder.poll(force=True)
            self.assertIn(evidence_id, json.dumps(current))
            intent = stop_run(log, "repeated_non_progress", [evidence_id], observed)
            self.assertEqual(_watchdog_validation(log, intent),
                             (False, "stale_observation"))

    def test_atomic_idempotent_request_and_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run.ndjson"
            first = stop_run(log, "repeated_non_progress", ["e1", "e2"], 7)
            duplicate = stop_run(log, "different_reason", ["other"], 99)
            self.assertEqual(first, duplicate)
            self.assertEqual(read_stop(log), first)
            resolved = resolve_stop(log, "cancelled", details={"signal": "SIGTERM"})
            self.assertEqual(resolved["resolution"], "cancelled")
            self.assertEqual(resolve_stop(log, "stale"), resolved)
            self.assertEqual(read_stop(log)["request_id"], first["request_id"])
            self.assertTrue(stop_path_for_log(log).is_file())

    def test_log_path_recovers_runwatchdog_uuid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            watchdog = root / "match.watchdog"
            watchdog.mkdir()
            (watchdog / "state.json").write_text(json.dumps({
                "version": 1, "run_id": "0123456789abcdef", "log_path": log.name,
            }), encoding="utf-8")
            intent = stop_run(log, "manual_operator_stop", [], 0)
            self.assertEqual(intent["run_id"], "0123456789abcdef")
            self.assertEqual(read_stop("0123456789abcdef", root=root)["request_id"],
                             intent["request_id"])

    def test_malformed_or_unbounded_intents_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "run.ndjson"
            with self.assertRaises(StopError):
                stop_run(log, "bad reason", [], 0)
            with self.assertRaises(StopError):
                stop_run(log, "stop", ["x"] * 33, 0)
            with self.assertRaises(StopError):
                stop_run(log, "stop", [], -1)
            stop_path_for_log(log).parent.mkdir()
            stop_path_for_log(log).write_text("[]", encoding="utf-8")
            with self.assertRaises(Exception):
                read_stop(log)

    def test_validation_natural_winner_stale_and_evidence(self):
        request = {"run_id": "run", "reason_code": "stuck", "observed_sequence": 3,
                   "evidence_ids": ["e1"]}
        self.assertEqual(validate_stop_request(request, run_id="run", current_sequence=4,
                                               evidence_validator=lambda item: item == "e1"),
                         (True, "validated"))
        self.assertEqual(validate_stop_request(request, run_id="run", current_sequence=2),
                         (False, "stale_observation"))
        self.assertEqual(validate_stop_request(request, run_id="run", terminal={"terminal_class": "gameplay"}),
                         (False, "natural_completion_wins"))
        self.assertEqual(validate_stop_request(request, run_id="run",
                                               evidence_validator=lambda _item: False),
                         (False, "stale_evidence"))


class ProcessTreeCleanupTests(unittest.TestCase):
    def test_cleanup_reaps_exited_parent_and_forces_setsid_child_only(self):
        """A parent can exit on SIGTERM while an owned setsid child ignores it."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "child.pid"
            script = root / "tree.py"
            script.write_text(
                "import os, signal, subprocess, sys, time\n"
                "def finish(_sig, _frame): raise SystemExit(0)\n"
                "signal.signal(signal.SIGTERM, finish)\n"
                "p=subprocess.Popen([sys.executable, '-c', "
                "'import os,signal,time; os.setsid(); signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
                "open(sys.argv[1], 'w').write(str(p.pid))\n"
                "time.sleep(30)\n", encoding="utf-8")
            target = subprocess.Popen([sys.executable, str(script), str(marker)],
                                       start_new_session=True)
            unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            try:
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                child_pid = int(marker.read_text())
                started = time.monotonic()
                cleanup = terminate_process_tree(target, grace_seconds=0.25,
                                                  poll_interval=0.01)
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 1.5)
                self.assertTrue(cleanup.forced)
                self.assertEqual(cleanup.remaining_pids, [])
                self.assertIsNotNone(target.poll())
                self.assertIsNone(unrelated.poll())
                # A killed child may remain briefly as a zombie, but it must
                # never remain live after the bounded cleanup returns.
                child_deadline = time.monotonic() + 1
                while time.monotonic() < child_deadline:
                    stat_path = Path(f"/proc/{child_pid}/stat")
                    if not stat_path.exists():
                        break
                    fields = stat_path.read_text().split()
                    if len(fields) > 2 and fields[2] == "Z":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("owned setsid child remained live after cleanup")
            finally:
                if target.poll() is None:
                    target.kill()
                    target.wait()
                if unrelated.poll() is None:
                    unrelated.terminate()
                    unrelated.wait(timeout=3)

    def test_owned_nested_processes_can_be_identified_by_session(self):
        """Fixture documents the ownership assumption used by supervisor cleanup."""
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "child.pid"
            script = Path(directory) / "tree.py"
            script.write_text(
                "import os, subprocess, sys, time\n"
                "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                "open(sys.argv[1], 'w').write(str(p.pid))\n"
                "time.sleep(30)\n", encoding="utf-8")
            proc = subprocess.Popen([sys.executable, str(script), str(marker)],
                                    start_new_session=True)
            try:
                deadline = time.monotonic() + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                child_pid = int(marker.read_text())
                self.assertEqual(os.getpgid(child_pid), os.getpgid(proc.pid))
            finally:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
