import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread

from .file_backend import run


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


if __name__ == "__main__":
    unittest.main()
