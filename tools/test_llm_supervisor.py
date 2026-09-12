import json
import tempfile
import os
import stat
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from .llm_supervisor import _watchdog_validation, run
from .watchdog_stop import read_stop, stop_run
from .run_watchdog import RunWatchdog
from .watchdog_observer import FakeObserverBackend


class SupervisorStopIntegrationTests(unittest.TestCase):
    def test_streaming_child_stop_is_terminal_without_restart(self):
        """A provider-like stream can be stopped while output is still arriving."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            marker = root / "streaming"
            foreign = root / "foreign-evidence"
            foreign.mkdir()
            script = root / "streaming.py"
            script.write_text(
                "import base64, json, os, sys, time\nfrom pathlib import Path\n"
                "root=Path(os.environ['NORRUST_EVIDENCE_DIR']); root.mkdir(parents=True, exist_ok=True)\n"
                "chunks=root/'chunks.ndjson'\n"
                "for i in range(1000):\n"
                " with chunks.open('a') as out: out.write(json.dumps({'data_b64': base64.b64encode(('data: chunk '+str(i)+'\\n\\n').encode()).decode()})+'\\n')\n"
                " if i == 2: Path(sys.argv[1]).write_text('ready')\n"
                " time.sleep(0.02)\n", encoding="utf-8")
            import threading
            result = []
            worker = threading.Thread(target=lambda: result.append(
                run([sys.executable, str(script), str(marker)], log, 2)))
            started = time.monotonic()
            with mock.patch.dict(os.environ, {
                    "NORRUST_EVIDENCE_DIR": str(foreign),
                    "NORRUST_REQUEST_CONTEXT_FILE": str(foreign / "context.json"),
            }):
                worker.start()
                deadline = started + 3
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                stop_run(log, "manual_operator_stop", [], 0)
                worker.join(timeout=8)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [4])
            self.assertTrue((root / "match.evidence" / "chunks.ndjson").is_file())
            self.assertFalse((foreign / "chunks.ndjson").exists())
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len([r for r in records if r.get("type") == "supervisor_attempt_start"]), 1)
            self.assertFalse(any(r.get("type") == "supervisor_restart" for r in records))
            terminal = next(r for r in records if r.get("type") == "terminal")
            self.assertEqual(terminal["terminal_class"], "observer_interrupted")
            self.assertTrue(terminal["remote_cancellation"] == "unknown")

class SupervisorObserverFenceTests(unittest.TestCase):
    def test_observer_stop_allows_sequence_drift_without_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            watchdog = root / "match.watchdog"
            watchdog.mkdir()
            evidence = "log:0:1:fixture"
            (watchdog / "state.json").write_text(json.dumps({
                "run_id": "run-uuid", "index": [{"evidence_id": evidence}],
            }))
            packet = {"observation_sequence": 5, "revision": 2,
                      "last_completed_turn": "turn-1",
                      "committed_action": {"batch_id": "batch-1", "revision": 2},
                      "current_request": {"harness_request_id": "request-1"},
                      "alerts": [{"identity": "incident"}], "evidence_ids": [evidence]}
            latest = dict(packet, observation_sequence=6)
            (watchdog / "journal.ndjson").write_text("\n".join(
                json.dumps({"type": "status", "status": value})
                for value in (packet, latest)) + "\n")
            intent = {"run_id": "run-uuid", "reason_code": "repeated_no_progress",
                      "evidence_ids": [evidence], "observed_sequence": 5}
            self.assertEqual(_watchdog_validation(log, intent), (True, "validated"))

    def test_observer_stop_is_stale_after_real_progress_even_with_old_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            watchdog = root / "match.watchdog"
            watchdog.mkdir()
            evidence = "log:0:1:fixture"
            (watchdog / "state.json").write_text(json.dumps({
                "run_id": "run-uuid", "index": [{"evidence_id": evidence}],
            }))
            packet = {"observation_sequence": 5, "revision": 2,
                      "last_completed_turn": "turn-1",
                      "committed_action": {"batch_id": "batch-1", "revision": 2},
                      "current_request": {"harness_request_id": "request-1"},
                      "alerts": [{"identity": "incident"}], "evidence_ids": [evidence]}
            progressed = dict(packet, observation_sequence=6, revision=3,
                              committed_action={"batch_id": "batch-2", "revision": 3})
            (watchdog / "journal.ndjson").write_text("\n".join(
                json.dumps({"type": "status", "status": value})
                for value in (packet, progressed)) + "\n")
            intent = {"run_id": "run-uuid", "reason_code": "repeated_no_progress",
                      "evidence_ids": [evidence], "observed_sequence": 5}
            self.assertEqual(_watchdog_validation(log, intent), (False, "stale_progress"))


class SupervisorObserverTests(unittest.TestCase):
    def test_observer_attaches_lazily_after_metadata_with_injected_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            script = root / "writer.py"
            script.write_text(
                "import json,sys,time\n"
                "with open(sys.argv[1], 'a') as stream:\n"
                " stream.write(json.dumps({'type':'metadata','conversation_id':'catalog-game'})+'\\n')\n"
                " stream.flush()\n"
                "time.sleep(.15)\n", encoding="utf-8")
            recorder = RunWatchdog(log, run_id="supervisor-uuid", poll_interval=0)
            backend = FakeObserverBackend([{
                "decision": "continue", "reason_code": "healthy",
                "evidence_ids": [], "explanation": "fixture"}])
            ticks = [0.0]
            result = run([sys.executable, str(script), str(log)], log, 0,
                         watchdog=recorder, poll_interval=.01,
                         watchdog_mode="observe", observer_backend=backend,
                         observer_clock=lambda: ticks.__setitem__(0, ticks[0] + 300) or ticks[0])
            self.assertEqual(result, 0)
            self.assertGreaterEqual(len(backend.payloads), 1)
            rows = [json.loads(line) for line in (root / "usage.ndjson").read_text().splitlines()]
            self.assertTrue(rows)
            self.assertTrue(all(row["call_role"] == "observer" for row in rows))
            self.assertTrue(all(row["game_id"] == "catalog-game" for row in rows))
    def test_real_process_tree_stop_is_durable_and_forced(self):
        """A SIGTERM-ignoring nested shell is cleaned up within the grace window."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            script = root / "hung.py"
            child_pid = root / "child.pid"
            script.write_text(
                "import os, signal, subprocess, sys, time\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "p=subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
                "open(sys.argv[1], 'w').write(str(p.pid))\n"
                "time.sleep(30)\n", encoding="utf-8")
            import threading
            result = []
            def execute():
                result.append(run([sys.executable, str(script), str(child_pid)], log, 0))
            worker = threading.Thread(target=execute)
            worker.start()
            deadline = time.monotonic() + 3
            while not child_pid.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(child_pid.exists())
            stop_run(log, "manual_operator_stop", [], 0)
            worker.join(timeout=8)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [4])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            terminal = next(record for record in records if record.get("type") == "terminal")
            self.assertEqual(terminal["terminal_class"], "observer_interrupted")
            self.assertFalse(terminal["gameplay_valid"])
            self.assertEqual(read_stop(log)["status"], "resolved")
class FinishedProcess:
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
        return self.returncode


class ProgressProcess:
    def __init__(self, log):
        self.log = log
        self.calls = 0
        self.returncode = None

    def poll(self):
        self.calls += 1
        if self.calls == 2:
            with self.log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "driver", "line": {
                    "type": "state", "state_revision": 7, "turn": 3}}) + "\n")
        if self.calls >= 3:
            self.returncode = 0
        return self.returncode


class SupervisorTests(unittest.TestCase):
    def test_stop_before_dispatch_does_not_spawn_or_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            marker = root / "spawned"
            script = root / "child.py"
            script.write_text(
                "from pathlib import Path\nimport sys,time\n"
                "Path(sys.argv[1]).write_text('spawned')\n"
                "time.sleep(30)\n", encoding="utf-8")
            intent = stop_run(log, "manual_operator_stop", [], 0)
            self.assertNotEqual(intent["run_id"], log.stem)
            self.assertEqual(run([sys.executable, str(script), str(marker)], log, 2), 4)
            self.assertFalse(marker.exists())
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len([r for r in records if r.get("type") == "supervisor_attempt_start"]), 1)
            self.assertFalse(any(r.get("type") == "supervisor_restart" for r in records))

    def test_game_end_before_client_terminal_wins_stop_race(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            marker = root / "game_end"
            script = root / "child.py"
            script.write_text(
                "import json,sys,time\nfrom pathlib import Path\n"
                "log=Path(sys.argv[1]); marker=Path(sys.argv[2])\n"
                "with log.open('a') as stream: stream.write(json.dumps({'type':'driver', 'line': {'type':'game_end', 'winner': 1, 'reason': 'winner'}})+'\\n')\n"
                "marker.write_text('ready')\n"
                "time.sleep(0.4)\n", encoding="utf-8")
            import threading
            result = []
            worker = threading.Thread(target=lambda: result.append(
                run([sys.executable, str(script), str(log), str(marker)], log, 0)))
            worker.start()
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            stop_run(log, "manual_operator_stop", [], 0)
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [0])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertFalse(any(r.get("type") == "observer_interrupted" for r in records))
            self.assertEqual(read_stop(log).get("resolution"), "natural_completion_wins")

    def test_open_child_is_polled_and_watchdog_observes_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            watchdog = RunWatchdog(log, "long", poll_interval=0)
            child = ProgressProcess(log)
            with mock.patch("subprocess.Popen", return_value=child):
                self.assertEqual(run(["client", "--log", str(log)], log, 0,
                                     watchdog=watchdog, poll_interval=0.01), 0)
            self.assertEqual(watchdog.status()["revision"], 7)
            self.assertGreaterEqual(child.calls, 3)

    def test_real_subprocess_signal_restarts_without_duplicate_progress(self):
        """Exercise the restart loop with a real child and durable progress file."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            progress = root / "progress"
            request = root / "requests"; request.mkdir()
            (request / "answer.json").write_text("{}")
            state = request / "state.json"
            state.write_text(json.dumps({"request_id":"r1","state":"completed","answer_path":"answer.json","metadata":{}}))
            script = root / "child.py"
            script.write_text(
                "import json, os, signal, sys\n"
                "from pathlib import Path\n"
                "log=Path(sys.argv[1]); progress=Path(sys.argv[2])\n"
                "n=int(progress.read_text()) if progress.exists() else 0\n"
                "if n == 0:\n"
                " progress.write_text('1')\n"
                " log.with_suffix('.ckpt').mkdir(exist_ok=True)\n"
                " (log.with_suffix('.ckpt')/'state.json').write_text('{}')\n"
                " log.write_text(json.dumps({'type':'checkpoint_ref','path':'state.json','digest':''})+'\\n')\n"
                " os.kill(os.getpid(), signal.SIGKILL)\n"
                "n += 1; progress.write_text(str(n))\n"
                "with log.open('a') as out: out.write(json.dumps({'type':'terminal','terminal_class':'gameplay','reason':'cap'})+'\\n')\n"
                "sys.exit(0)\n",
                encoding="utf-8")
            result = run([sys.executable, str(script), str(log), str(progress)], log, 1, state)
            self.assertEqual(result, 0)
            self.assertEqual(progress.read_text(), "2")
            records = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertGreaterEqual(len([r for r in records if r.get('type') == 'supervisor_attempt_start']), 1)
            self.assertEqual(len([r for r in records if r.get('type') == 'terminal']), 1)
    def test_signal_restart_uses_resume_log_once(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            request = Path(directory) / "request"; request.mkdir()
            (request / "answer.json").write_text("{}")
            state = request / "state.json"
            state.write_text(json.dumps({"request_id":"r1","state":"completed","answer_path":"answer.json","metadata":{}}))
            checkpoint_dir = log.with_suffix(".ckpt")
            checkpoint_dir.mkdir()
            (checkpoint_dir / "0-0-model-valid.json").write_text("{}")
            def result(*_args, **_kwargs):
                if process.call_count == 1:
                    return FinishedProcess(-9)
                with log.open("a") as stream:
                    stream.write(json.dumps({"type":"terminal","terminal_class":"gameplay"})+"\n")
                return FinishedProcess(0)
            with mock.patch("subprocess.Popen", side_effect=result) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 3, state), 0)
            self.assertEqual(process.call_count, 2)
            self.assertIn("--resume-log", process.call_args_list[1].args[0])
            self.assertIn('"type": "supervisor_attempt_start"', log.read_text())

    def test_model_invalid_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            request = Path(directory) / "request"; request.mkdir()
            (request / "answer.json").write_text("{}")
            state = request / "state.json"
            state.write_text(json.dumps({"request_id":"r1","state":"completed","answer_path":"answer.json","metadata":{}}))
            log.write_text(json.dumps({"type": "terminal", "terminal_class": "model_invalid"}) + "\n")
            with mock.patch("subprocess.Popen", return_value=FinishedProcess(2)) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 3), 2)
            self.assertEqual(process.call_count, 1)

    def test_legacy_model_error_is_not_restarted_as_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            log.write_text(json.dumps({
                "type": "model_error",
                "terminal_class": "model_invalid",
            }) + "\n")
            with mock.patch("subprocess.Popen", return_value=FinishedProcess(2)) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 3), 2)
            self.assertEqual(process.call_count, 1)

    def test_budget_stop_is_reported_and_not_restarted(self):
        for record_type in ("budget_interrupted", "model_error"):
            for returncode in (3, -9):
                with self.subTest(record_type=record_type, returncode=returncode), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    log = root / "match.ndjson"
                    request = root / "request"; request.mkdir()
                    (request / "answer.json").write_text("{}")
                    state = request / "state.json"
                    state.write_text(json.dumps({
                        "request_id": "r1", "state": "completed", "answer_path": "answer.json",
                        "metadata": {},
                    }))
                    checkpoint_dir = log.with_suffix(".ckpt")
                    checkpoint_dir.mkdir()
                    (checkpoint_dir / "state.json").write_text("{}")

                    def child(*_args, **_kwargs):
                        record = {"type": record_type, "terminal_class": "model_invalid"}
                        if record_type == "model_error":
                            record.update(reason="budget_interrupted",
                                          code="max_game_total_tokens_exhausted")
                        with log.open("a") as stream:
                            stream.write(json.dumps(record) + "\n")
                        return FinishedProcess(returncode)

                    with mock.patch("subprocess.Popen", side_effect=child) as process:
                        self.assertEqual(run(["client", "--log", str(log)], log, 3, state), returncode)
                    self.assertEqual(process.call_count, 1)
                    outcome = next(json.loads(line) for line in log.read_text().splitlines()
                                   if json.loads(line).get("type") == "supervisor_attempt_outcome")
                    self.assertEqual(outcome["terminal_class"], "budget_interrupted")
                    self.assertEqual(outcome["recovery_decision"], "stop")

    def test_restart_limit_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            checkpoint_dir = log.with_suffix(".ckpt")
            checkpoint_dir.mkdir()
            (checkpoint_dir / "0-0-model-valid.json").write_text("{}")
            request = Path(directory) / "request"; request.mkdir()
            (request / "answer.json").write_text("{}")
            state = request / "state.json"
            state.write_text(json.dumps({"request_id":"r1","state":"completed","answer_path":"answer.json","metadata":{}}))
            with mock.patch("subprocess.Popen", return_value=FinishedProcess(-9)) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 2, state), -9)
            self.assertEqual(process.call_count, 3)


if __name__ == "__main__":
    unittest.main()
