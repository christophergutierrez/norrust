"""Exercise maintained CLI entry points through offline subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CliCommandTests(unittest.TestCase):
    def test_backend_starts_and_resumes_with_explicit_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "codex"
            native.write_text(f"#!{sys.executable}\n" +
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['TEST_CODEX_CAPTURE']).write_text(json.dumps(sys.argv))\n"
                "print(json.dumps({'type':'thread.started','thread_id':'offline-thread'}))\n"
                "print(json.dumps({'type':'item.completed','item':"
                "{'type':'agent_message','text':'[{\\\"action\\\":\\\"EndTurn\\\"}]'}}))\n"
                "print(json.dumps({'type':'turn.completed'}))\n")
            native.chmod(0o755)
            for mode in ("module", "script"):
                with self.subTest(mode=mode):
                    run_root = root / mode
                    run_root.mkdir()
                    env = {key: value for key, value in os.environ.items()
                           if not key.startswith("NORRUST_CODEX_")}
                    env.update(PATH=str(root) + os.pathsep + env.get("PATH", ""),
                               TEST_CODEX_CAPTURE=str(run_root / "argv.json"),
                               NORRUST_CODEX_SESSION_FILE=str(run_root / "session.json"),
                               NORRUST_CODEX_ARTIFACT_DIR=str(run_root / "artifacts"))
                    entry = ["-m", "tools.codex_backend"] if mode == "module" else ["tools/codex_backend.py"]
                    for turn, (model, effort) in enumerate(
                            (("test-model", "medium"), ("another-model", "low")), start=1):
                        env.update(NORRUST_CODEX_MODEL=model, NORRUST_CODEX_REASONING_EFFORT=effort)
                        result = subprocess.run([sys.executable, *entry], cwd=ROOT, env=env,
                            input="canonical prompt\n", capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        reply = json.loads(result.stdout)
                        self.assertEqual(json.loads(reply["text"]), [{"action": "EndTurn"}])
                        command = json.loads((run_root / "argv.json").read_text())
                        flag = "--model" if turn == 1 else "-m"
                        self.assertEqual(command[command.index(flag) + 1], model)
                        self.assertEqual(command[command.index("-c") + 1], f"model_reasoning_effort={effort}")
                        if turn == 2:
                            self.assertEqual(command[1:4], ["exec", "resume", "offline-thread"])
                        self.assertEqual(reply["cache"]["requested_model"], model)
                        self.assertIsNone(reply["cache"]["runtime_model"])
                        session = json.loads((run_root / "session.json").read_text())
                        self.assertEqual(session["requested_model"], model)
                        self.assertEqual(session["requested_reasoning_effort"], effort)
                        self.assertEqual(session["turns"], turn)
                        self.assertEqual((run_root / "artifacts" / f"{turn:05d}-request.txt").read_text(),
                                         "canonical prompt\n")

    def test_report_commands_emit_exactly_one_record_per_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            log.write_text('{"type":"terminal","reason":"max_turns"}\n')
            for entry in (["-m", "tools.match_report"], ["tools/match_report.py"]):
                with self.subTest(entry=entry):
                    result = subprocess.run([sys.executable, *entry, str(log)], cwd=ROOT,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    records = [json.loads(line) for line in result.stdout.splitlines()]
                    self.assertEqual([record["log"] for record in records], [str(log)])

    def test_backend_configuration_errors_exit_cleanly_before_dispatch(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("NORRUST_CODEX_")}
        for entry in (["-m", "tools.codex_backend"], ["tools/codex_backend.py"]):
            for settings, missing in (({}, "NORRUST_CODEX_MODEL"),
                                      ({"NORRUST_CODEX_MODEL": "test-model"}, "NORRUST_CODEX_SESSION_FILE")):
                with self.subTest(entry=entry, missing=missing):
                    result = subprocess.run([sys.executable, *entry], input="prompt", cwd=ROOT,
                                            env={**env, **settings}, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(f"{missing} is required", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(result.stdout, "")
