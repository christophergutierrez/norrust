import json
import subprocess
import sys
import tempfile
import unittest

from tools.luna_request_journal import RequestConflict, RequestJournal, RequestStateError, read_state


class RequestJournalTests(unittest.TestCase):
    def test_lifecycle_is_durable_and_events_are_ordered(self):
        with tempfile.TemporaryDirectory() as directory:
            with RequestJournal(directory, "match-1") as journal:
                request = journal.prepare({"match_id": "match-1", "deadline": 12.5})
                request.append_event({"type": "thread.started", "thread_id": "native-1"})
                request.mark_dispatched(prompt_digest="abc")
                request.append_event({"type": "item.completed"})
                request.complete({"text": "[]"}, reply_id="reply-1")
                request_dir = request.directory
                request.close()

            state = read_state(request_dir)
            self.assertEqual("completed", state["state"])
            self.assertEqual("reply-1", state["reply_id"])
            self.assertEqual({"text": "[]"}, json.loads((request_dir / "answer.json").read_text()))
            events = [json.loads(line) for line in (request_dir / "events.ndjson").read_text().splitlines()]
            self.assertEqual(["state", "native_event", "state", "native_event", "state"],
                             [event["kind"] for event in events])
            self.assertEqual([0, 0, 1, 1, 2], [event["sequence"] for event in events])

    def test_request_directories_are_unique_and_terminal_states_are_final(self):
        with tempfile.TemporaryDirectory() as directory:
            with RequestJournal(directory, "match-1") as journal:
                first = journal.prepare()
                first.mark_dispatched()
                first.fail(error="boom")
                first.close()

            with RequestJournal(directory, "match-1") as journal:
                second = journal.prepare()
                second.interrupt(reason="deadline")
                second.close()

            self.assertNotEqual(first.request_id, second.request_id)
            with self.assertRaises(RequestStateError):
                first.mark_dispatched()
            self.assertEqual("failed", read_state(first.directory)["state"])

    def test_second_writer_cannot_enter_until_first_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = RequestJournal(directory, "same-match")
            journal.acquire()
            try:
                script = (
                    "from tools.luna_request_journal import RequestJournal, RequestConflict; "
                    f"j=RequestJournal({directory!r}, 'same-match'); "
                    "\ntry: j.acquire()\nexcept RequestConflict: print('conflict')"
                )
                result = subprocess.run([sys.executable, "-c", script], capture_output=True,
                                        text=True, check=True)
                self.assertEqual("conflict\n", result.stdout)
            finally:
                journal.release()

            with RequestJournal(directory, "same-match") as available:
                handle = available.prepare()
                handle.close()

    def test_invalid_transition_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory() as directory:
            with RequestJournal(directory, "match-1") as journal:
                request = journal.prepare()
                with self.assertRaises(RequestStateError):
                    request.complete("too-early")
                self.assertEqual("prepared", read_state(request.directory)["state"])
                request.close()

    def test_unknown_is_a_durable_terminal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            with RequestJournal(directory, "match-1") as journal:
                request = journal.prepare()
                request.mark_dispatched()
                request.mark_unknown(reason="process disappeared")
                request.close()
            self.assertEqual("unknown", read_state(request.directory)["state"])


if __name__ == "__main__":
    unittest.main()
