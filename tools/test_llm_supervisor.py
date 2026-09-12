import json
import tempfile
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from .llm_supervisor import run
from .run_watchdog import RunWatchdog


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
