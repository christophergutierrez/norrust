import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]

from .file_backend import run
from .publish_reply import PublishError, publish_reply


class FileBackendTests(unittest.TestCase):
    def test_prompt_is_unchanged_and_reply_is_enveloped(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            prompt = "literal\nDRAFT_RESULT danger_after=unknown\n"
            result = {}

            def serve():
                result["value"] = run(directory, prompt, timeout=2)

            thread = Thread(target=serve)
            thread.start()
            deadline = time.monotonic() + 1
            waiting = None
            while waiting is None and time.monotonic() < deadline:
                waiting = next(directory.glob("waiting_*"), None)
                if waiting is None:
                    time.sleep(0.001)
            self.assertIsNotNone(waiting)
            request_id = waiting.name.removeprefix("waiting_")
            self.assertEqual((directory / f"prompt_{request_id}.txt").read_text(), prompt)
            (directory / f"reply_{request_id}.txt").write_text("[{\"action\":\"EndTurn\"}]\n")
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(json.loads(result["value"])["text"], "[{\"action\":\"EndTurn\"}]\n")

    def test_old_reply_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "reply_000000-old.txt").write_text("stale")
            with self.assertRaises(TimeoutError):
                run(directory, "new", timeout=0.01, poll=0.001)

    def test_invalid_then_corrected_reply_via_publish_reply_reaches_backend_once(self):
        # A player using tools.publish_reply as the local pre-publication
        # validator, rather than writing reply_<ID>.txt directly, must still
        # produce exactly one delivered reply to this backend: the raw
        # invalid attempt never crosses the handshake, and no driver action
        # results from it.
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            prompt = "the complete client prompt\n"
            result = {}

            def serve():
                result["value"] = run(directory, prompt, timeout=2)

            thread = Thread(target=serve)
            thread.start()
            deadline = time.monotonic() + 1
            waiting = None
            while waiting is None and time.monotonic() < deadline:
                waiting = next(directory.glob("waiting_*"), None)
                if waiting is None:
                    time.sleep(0.001)
            self.assertIsNotNone(waiting)
            request_id = waiting.name.removeprefix("waiting_")

            invalid = (directory / "draft1.tmp")
            invalid.write_text(json.dumps({
                "actions": [{"action": "EndTurn"}],
                "decisions": [{"orders": [0], "rules": ["T8"], "expected": "e", "risk": ""}],
            }))
            with self.assertRaises(PublishError):
                publish_reply(invalid, directory, request_id)
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())
            self.assertTrue(thread.is_alive(), "backend must still be waiting after a rejected draft")

            corrected = (directory / "draft2.tmp")
            corrected_text = json.dumps({
                "actions": [{"action": "EndTurn"}],
                "decisions": [{"orders": [0], "rules": ["T8"], "expected": "e", "risk": "none"}],
            })
            corrected.write_text(corrected_text)
            publish_reply(corrected, directory, request_id)

            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(json.loads(result["value"])["text"], corrected_text)



class HarnessRequestLinkageTests(unittest.TestCase):
    """The transport mints its own request id from a prompt hash; that is not the
    harness request that owns the spending. Host inference calls can only be
    attributed if the handshake carries the harness identity and the window in
    which its prompt was open.
    """

    def _run_backend(self, reqs, env, prompt="PROMPT"):
        proc = subprocess.Popen(
            [sys.executable, "-m", "tools.file_backend", "--directory", str(reqs),
             "--timeout", "20"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, cwd=str(ROOT), env=env)

        def answer():
            for _ in range(400):
                markers = list(reqs.glob("waiting_*"))
                if markers:
                    rid = markers[0].name[len("waiting_"):]
                    (reqs / f"reply_{rid}.txt").write_text('[{"action":"EndTurn"}]')
                    return
                time.sleep(0.02)

        worker = threading.Thread(target=answer)
        worker.start()
        out, _ = proc.communicate(prompt, timeout=30)
        worker.join()
        return out

    def test_handshake_carries_the_harness_request_and_its_open_window(self):
        from .llm_client import write_request_context
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); reqs = root / "requests"; reqs.mkdir()
            ctx = root / "context.json"
            write_request_context(ctx, {
                "harness_request_id": "conv:request:7", "request_sequence": 7,
                "conversation_id": "conv", "side": 0, "side_turn_id": "conv:turn:3",
                "state_revision": 42, "requested_model": "test-model",
                "requested_reasoning_effort": "medium", "prompt_sha256": "x",
                "prompt_bytes": 1, "dispatched_at": "2026-09-09T00:00:00+00:00"})
            self._run_backend(reqs, dict(os.environ, NORRUST_REQUEST_CONTEXT_FILE=str(ctx)))
            record = json.loads((reqs / "handshake_log.ndjson").read_text().splitlines()[0])
            self.assertEqual(record["harness_request_id"], "conv:request:7")
            self.assertEqual(record["side_turn_id"], "conv:turn:3")
            self.assertEqual(record["state_revision"], 42)
            # The transport id is its own; it must not be mistaken for the harness id.
            self.assertNotEqual(record["request_id"], record["harness_request_id"])
            self.assertLess(record["published_at"], record["answered_at"])
            # No prompt text or credentials in the accounting record.
            self.assertNotIn("PROMPT", json.dumps(record))

    def test_absent_context_still_serves_the_game_and_stays_unlinked(self):
        with tempfile.TemporaryDirectory() as td:
            reqs = Path(td) / "requests"; reqs.mkdir()
            env = dict(os.environ); env.pop("NORRUST_REQUEST_CONTEXT_FILE", None)
            out = self._run_backend(reqs, env)
            self.assertIn("EndTurn", out)
            record = json.loads((reqs / "handshake_log.ndjson").read_text().splitlines()[0])
            # Unlinked, never guessed: accounting degrades, gameplay does not.
            self.assertNotIn("harness_request_id", record)


if __name__ == "__main__":
    unittest.main()
