import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .llm_supervisor import run


class SupervisorTests(unittest.TestCase):
    def test_signal_restart_uses_resume_log_once(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            checkpoint_dir = log.with_suffix(".ckpt")
            checkpoint_dir.mkdir()
            (checkpoint_dir / "0-0-model-valid.json").write_text("{}")
            results = [mock.Mock(returncode=-9), mock.Mock(returncode=0)]
            with mock.patch("subprocess.run", side_effect=results) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 3), 0)
            self.assertEqual(process.call_count, 2)
            self.assertIn("--resume-log", process.call_args_list[1].args[0])
            self.assertIn('"type": "supervisor_attempt"', log.read_text())

    def test_model_invalid_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            log.write_text(json.dumps({"type": "terminal", "terminal_class": "model_invalid"}) + "\n")
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=2)) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 3), 2)
            self.assertEqual(process.call_count, 1)

    def test_legacy_model_error_is_not_restarted_as_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            log.write_text(json.dumps({
                "type": "model_error",
                "terminal_class": "model_invalid",
            }) + "\n")
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=2)) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 3), 2)
            self.assertEqual(process.call_count, 1)

    def test_restart_limit_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            checkpoint_dir = log.with_suffix(".ckpt")
            checkpoint_dir.mkdir()
            (checkpoint_dir / "0-0-model-valid.json").write_text("{}")
            with mock.patch("subprocess.run", return_value=mock.Mock(returncode=-9)) as process:
                self.assertEqual(run(["client", "--log", str(log)], log, 2), -9)
            self.assertEqual(process.call_count, 3)


if __name__ == "__main__":
    unittest.main()
