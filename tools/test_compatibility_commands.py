"""Exercise public entry points as subprocesses, including legacy aliases."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CompatibilityCommandTests(unittest.TestCase):
    def test_backend_commands_complete_using_offline_native_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "codex"
            native.write_text(f"#!{sys.executable}\n" +
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['TEST_CODEX_CAPTURE']).write_text(json.dumps(sys.argv))\n"
                "print(json.dumps({'type':'thread.started','thread_id':'offline-thread'}))\n"
                "print(json.dumps({'type':'item.completed','item':"
                "{'type':'agent_message','text':'[{\"action\":\"EndTurn\"}]'}}))\n"
                "print(json.dumps({'type':'turn.completed'}))\n")
            native.chmod(0o755)
            for module in ("codex_backend", "luna_backend"):
                for mode in ("module", "script"):
                    with self.subTest(module=module, mode=mode):
                        run_root = root / f"{module}-{mode}"
                        run_root.mkdir()
                        env = {key: value for key, value in os.environ.items()
                               if not key.startswith(("NORRUST_CODEX_", "NORRUST_LUNA_"))}
                        env.update(PATH=str(root) + os.pathsep + env.get("PATH", ""),
                                   TEST_CODEX_CAPTURE=str(run_root / "argv.json"))
                        legacy = module == "luna_backend"
                        prefix = "NORRUST_LUNA_" if legacy else "NORRUST_CODEX_"
                        env[prefix + "SESSION_FILE"] = str(run_root / "session.json")
                        env[prefix + "ARTIFACT_DIR"] = str(run_root / "artifacts")
                        if not legacy:
                            env[prefix + "MODEL"] = "test-model"
                            env[prefix + "REASONING_EFFORT"] = "medium"
                        entry = ["-m", f"tools.{module}"] if mode == "module" else [f"tools/{module}.py"]
                        result = subprocess.run([sys.executable, *entry], cwd=ROOT, env=env,
                            input="canonical prompt\n", capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        reply = json.loads(result.stdout)
                        self.assertEqual(json.loads(reply["text"]), [{"action": "EndTurn"}])
                        expected_model = "gpt-5.6-luna" if legacy else "test-model"
                        command = json.loads((run_root / "argv.json").read_text())
                        self.assertEqual(command[command.index("--model") + 1], expected_model)
                        self.assertEqual(reply["cache"]["requested_model"], expected_model)
                        self.assertIsNone(reply["cache"]["runtime_model"])
                        self.assertEqual((run_root / "artifacts" / "00001-request.txt").read_text(),
                                         "canonical prompt\n")

    def test_report_commands_emit_exactly_one_record_per_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            log.write_text('{"type":"terminal","reason":"max_turns"}\n')
            for module in ("match_report", "luna_report"):
                for entry in (["-m", f"tools.{module}"], [f"tools/{module}.py"]):
                    with self.subTest(entry=entry):
                        result = subprocess.run([sys.executable, *entry, str(log)], cwd=ROOT,
                                                capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        records = [json.loads(line) for line in result.stdout.splitlines()]
                        self.assertEqual([record["log"] for record in records], [str(log)])

    def test_backend_commands_preserve_configuration_error_exit_status(self):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("NORRUST_CODEX_", "NORRUST_LUNA_"))}
        env["NORRUST_CODEX_MODEL"] = "test-model"
        for module in ("codex_backend", "luna_backend"):
            for entry in (["-m", f"tools.{module}"], [f"tools/{module}.py"]):
                with self.subTest(entry=entry):
                    result = subprocess.run([sys.executable, *entry], input="prompt", cwd=ROOT,
                                            env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("NORRUST_CODEX_SESSION_FILE is required", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(result.stdout, "")
