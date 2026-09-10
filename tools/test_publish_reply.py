import json
import tempfile
import unittest
from pathlib import Path
from threading import Barrier, Thread
from typing import Any

from .publish_reply import PublishError, VALIDATION_LOG_NAME, publish_reply


def _make_request(directory: Path, request_id: str = "000001-abc123") -> str:
    (directory / f"prompt_{request_id}.txt").write_text("prompt text", encoding="utf-8")
    (directory / f"waiting_{request_id}").write_text(json.dumps({"request_id": request_id}), encoding="utf-8")
    return request_id


def _pending(directory: Path, text: str, name: str = "reply.tmp") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _validation_records(directory: Path) -> list[dict]:
    log = directory / VALIDATION_LOG_NAME
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


class PublishReplyTests(unittest.TestCase):
    def test_valid_action_envelope_publishes(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = json.dumps({"actions": [{"action": "EndTurn"}],
                               "decisions": [{"orders": [0], "rules": ["T8"],
                                              "expected": "end the turn", "risk": "none"}]})
            pending = _pending(directory, text)
            resolved = publish_reply(pending, directory, request_id)
            self.assertEqual(resolved, request_id)
            self.assertEqual((directory / f"reply_{request_id}.txt").read_text(encoding="utf-8"), text)
            records = _validation_records(directory)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "valid")
            self.assertIsNone(records[0]["error"])

    def test_eligible_inspection_publishes_without_decisions(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = json.dumps({"tool": "inspect_unit", "unit_id": 12})
            pending = _pending(directory, text)
            publish_reply(pending, directory, request_id)
            self.assertEqual((directory / f"reply_{request_id}.txt").read_text(encoding="utf-8"), text)
            self.assertEqual(_validation_records(directory)[0]["status"], "not_applicable")

    def test_bare_action_array_publishes_as_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = json.dumps([{"action": "EndTurn"}])
            pending = _pending(directory, text)
            publish_reply(pending, directory, request_id)
            self.assertEqual(_validation_records(directory)[0]["status"], "missing")

    def test_malformed_json_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            pending = _pending(directory, "{not json")
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
            self.assertIn("not valid JSON", str(ctx.exception))
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())
            records = _validation_records(directory)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "invalid")

    def test_unknown_rule_id_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = json.dumps({"actions": [{"action": "EndTurn"}],
                               "decisions": [{"orders": [0], "rules": ["NOPE"],
                                              "expected": "e", "risk": "r"}]})
            pending = _pending(directory, text)
            with self.assertRaises(PublishError):
                publish_reply(pending, directory, request_id)
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())

    def test_missing_action_coverage_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = json.dumps({"actions": [{"action": "EndTurn"}, {"action": "Move"}],
                               "decisions": [{"orders": [0], "rules": ["T8"],
                                              "expected": "e", "risk": "r"}]})
            pending = _pending(directory, text)
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
            self.assertIn("cover every authored action", str(ctx.exception))

    def test_empty_risk_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = json.dumps({"actions": [{"action": "EndTurn"}],
                               "decisions": [{"orders": [0], "rules": ["T8"],
                                              "expected": "e", "risk": ""}]})
            pending = _pending(directory, text)
            with self.assertRaises(PublishError):
                publish_reply(pending, directory, request_id)

    def test_overlong_multibyte_risk_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            # A multibyte character that pushes the UTF-8 byte length over 240
            # while the character count alone would look small.
            oversized_risk = "é" * 121  # 2 bytes each => 242 bytes
            text = json.dumps({"actions": [{"action": "EndTurn"}],
                               "decisions": [{"orders": [0], "rules": ["T8"],
                                              "expected": "e", "risk": oversized_risk}]})
            pending = _pending(directory, text)
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
    def test_single_fenced_json_with_prose_publishes(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = (
                "Here is my move proposal:\n"
                "```json\n"
                '{"actions": [{"action": "EndTurn"}]}\n'
                "```\n"
                "Hope this ends the turn cleanly."
            )
            pending = _pending(directory, text)
            resolved = publish_reply(pending, directory, request_id)
            self.assertEqual(resolved, request_id)
            self.assertEqual((directory / f"reply_{request_id}.txt").read_text(encoding="utf-8"), text)
            records = _validation_records(directory)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "missing")

    def test_multiple_fences_do_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = (
                "```json\n"
                '{"actions": [{"action": "EndTurn"}]}\n'
                "```\n"
                "Or alternatively:\n"
                "```json\n"
                '{"actions": [{"action": "DoneWithImportantMoves"}]}\n'
                "```\n"
            )
            pending = _pending(directory, text)
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
            self.assertIn("multiple candidate payloads", str(ctx.exception))
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())

    def test_truncated_fence_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = (
                "```json\n"
                '{"actions": [{"action": "EndTurn"}]}\n'
            )
            pending = _pending(directory, text)
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
            self.assertIn("truncated code fence", str(ctx.exception))
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())

    def test_greedy_braces_without_fence_do_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = 'Here is the move: {"actions": [{"action": "EndTurn"}]} please execute.'
            pending = _pending(directory, text)
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
            self.assertIn("not valid JSON", str(ctx.exception))
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())

    def test_unsupported_root_shape_does_not_publish(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            text = '```json\n"just a string"\n```'
            pending = _pending(directory, text)
            with self.assertRaises(PublishError) as ctx:
                publish_reply(pending, directory, request_id)
            self.assertIn("unsupported response shape", str(ctx.exception))
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())

    def test_invalid_then_corrected_reaches_backend_exactly_once(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            bad = json.dumps({"actions": [{"action": "EndTurn"}],
                              "decisions": [{"orders": [0], "rules": ["T8"],
                                             "expected": "e", "risk": ""}]})
            with self.assertRaises(PublishError):
                publish_reply(_pending(directory, bad, "attempt1.tmp"), directory, request_id)
            self.assertFalse((directory / f"reply_{request_id}.txt").exists())
            good = json.dumps({"actions": [{"action": "EndTurn"}],
                               "decisions": [{"orders": [0], "rules": ["T8"],
                                              "expected": "e", "risk": "none"}]})
            publish_reply(_pending(directory, good, "attempt2.tmp"), directory, request_id)
            self.assertEqual((directory / f"reply_{request_id}.txt").read_text(encoding="utf-8"), good)
            records = _validation_records(directory)
            self.assertEqual([r["status"] for r in records], ["invalid", "valid"])
            self.assertEqual(records[0]["request_id"], request_id)
            self.assertEqual(records[1]["request_id"], request_id)
            # The raw invalid attempt bytes remain visible for the report.
            self.assertNotEqual(records[0]["attempt_sha256"], records[1]["attempt_sha256"])

    def test_no_overwrite_of_earlier_reply(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            first = json.dumps({"actions": [{"action": "EndTurn"}]})
            publish_reply(_pending(directory, first, "a.tmp"), directory, request_id)
            second = json.dumps({"actions": [{"action": "DoneWithImportantMoves"}]})
            with self.assertRaises(PublishError) as ctx:
                publish_reply(_pending(directory, second, "b.tmp"), directory, request_id)
            self.assertIn("already published", str(ctx.exception))
            self.assertEqual((directory / f"reply_{request_id}.txt").read_text(encoding="utf-8"), first)

    def test_concurrent_publication_cannot_replace_a_reply(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            request_id = _make_request(directory)
            texts = [json.dumps({"actions": [{"action": "EndTurn"}]}),
                     json.dumps({"actions": [{"action": "DoneWithImportantMoves"}]})]
            pendings = [_pending(directory, texts[0], "race0.tmp"),
                        _pending(directory, texts[1], "race1.tmp")]
            barrier = Barrier(2)
            outcomes: list[Any] = [None, None]

            def attempt(index: int) -> None:
                barrier.wait()
                try:
                    outcomes[index] = ("ok", publish_reply(pendings[index], directory, request_id))
                except PublishError as exc:
                    outcomes[index] = ("error", str(exc))

            threads = [Thread(target=attempt, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            kinds = [outcome[0] for outcome in outcomes]
            self.assertEqual(sorted(kinds), ["error", "ok"])
            published_text = (directory / f"reply_{request_id}.txt").read_text(encoding="utf-8")
            self.assertIn(published_text, texts)

    def test_backend_diagnoses_a_reply_that_bypassed_publish_reply(self):
        # A backend or player may still write reply_<ID>.txt directly. The
        # helper is not the only authority: annotation_for_response (used by
        # both this module and tools.llm_client) still reports the same
        # error, so no inspection through publish_reply is required to see it.
        from .decision_annotations import annotation_for_response
        text = json.dumps({"actions": [{"action": "EndTurn"}],
                           "decisions": [{"orders": [0], "rules": ["T8"],
                                          "expected": "e", "risk": ""}]})
        annotation = annotation_for_response(text)
        self.assertEqual(annotation["status"], "invalid")
        self.assertIn("240 UTF-8 bytes", annotation["error"])

    def test_no_pending_marker_raises(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            pending = _pending(directory, json.dumps({"actions": [{"action": "EndTurn"}]}))
            with self.assertRaises(PublishError):
                publish_reply(pending, directory)

    def test_unknown_request_id_raises(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            pending = _pending(directory, json.dumps({"actions": [{"action": "EndTurn"}]}))
            with self.assertRaises(PublishError):
                publish_reply(pending, directory, "nonexistent")


if __name__ == "__main__":
    unittest.main()
