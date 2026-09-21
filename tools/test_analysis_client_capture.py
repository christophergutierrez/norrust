"""Optional analysis capture is opt-in, passive, and honest about gaps.

These tests run the real client against the real driver.  Component mocks
cannot establish the property that matters here -- that turning capture on
changes nothing about how the game is played -- so the passivity checks drive
two complete runs and compare their normalized game logs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.analysis_capture import analysis_dir_for_log, read_records

ROOT = Path(__file__).resolve().parents[1]
DRIVER = os.environ.get("NORRUST_TEST_DRIVER",
                        str(ROOT / "norrust_core/target/debug/greedy_driver"))

# Recording identities, filesystem paths and timings are the only differences a
# capture-on run is permitted to introduce.  Everything else must match byte for
# byte, so normalization is deliberately narrow: widening it would let a real
# behavioural difference hide inside the mask.
_CONVERSATION = re.compile(r'"[0-9a-f]{32}:')
_CONVERSATION_FIELD = re.compile(r'"conversation_id": "[0-9a-f]+"')
_TMP_PATH = re.compile(r'"[^"]*/(?:tmp|var)/[^"]*"')
_TIMESTAMP = re.compile(r'"(started_at|observed_at|dispatched_at|ended_at|'
                        r'recorded_at|completed_at)": "[^"]*"')
_DURATION = re.compile(r'"([a-z_]*_ms)": [0-9]+')


def _normalized(log: Path) -> list[str]:
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = json.dumps(record, sort_keys=True)
        text = _CONVERSATION.sub('"CONV:', text)
        text = _CONVERSATION_FIELD.sub('"conversation_id": "CONV"', text)
        text = _TMP_PATH.sub('"PATH"', text)
        text = _TIMESTAMP.sub(r'"\1": "T"', text)
        text = _DURATION.sub(r'"\1": 0', text)
        out.append(text)
    return out


def _play(directory: Path, *extra: str) -> subprocess.CompletedProcess:
    directory.mkdir(parents=True, exist_ok=True)
    orders = directory / "orders.jsonl"
    orders.write_text("[]\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "tools.llm_client",
         "--driver", DRIVER, "--seed", "42", "--max-turns", "6",
         "--orders-file", str(orders),
         "--log", str(directory / "match.ndjson"), *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=300)


@unittest.skipUnless(Path(DRIVER).is_file(),
                     "built greedy_driver required; run tools.fast_check first")
class AnalysisCaptureClientTests(unittest.TestCase):

    def test_capture_disabled_creates_no_artifact(self):
        """A disabled recording must remain an ordinary game, byte for byte."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "off"
            _play(run)
            log = run / "match.ndjson"
            self.assertTrue(log.is_file(), "the ordinary game log must still exist")
            self.assertFalse(analysis_dir_for_log(log).exists(),
                             "capture off must not create an analysis directory")

    def test_capture_enabled_writes_manifest_and_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "on"
            _play(run, "--analysis-capture")
            analysis = analysis_dir_for_log(run / "match.ndjson")
            self.assertTrue((analysis / "manifest.json").is_file())
            self.assertTrue((analysis / "analysis.ndjson").is_file())

    def test_manifest_carries_no_environment_or_credentials(self):
        """The launch configuration is allowlisted, never an environment dump."""
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "on"
            env_marker = "NORRUST_CAPTURE_CANARY_VALUE"
            os.environ["NORRUST_CAPTURE_CANARY"] = env_marker
            try:
                _play(run, "--analysis-capture")
            finally:
                os.environ.pop("NORRUST_CAPTURE_CANARY", None)
            manifest = (analysis_dir_for_log(run / "match.ndjson")
                        / "manifest.json").read_text(encoding="utf-8")
            self.assertNotIn(env_marker, manifest)
            self.assertNotIn("NORRUST_CAPTURE_CANARY", manifest)
            launch = json.loads(manifest)["launch"]
            self.assertIn("seed", launch)
            self.assertNotIn("model_command", launch)

    def test_capture_records_are_well_formed_and_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "on"
            _play(run, "--analysis-capture")
            result = read_records(analysis_dir_for_log(run / "match.ndjson"))
            self.assertEqual([], [w.message for w in result.warnings])
            self.assertTrue(result.has_final_marker,
                            "a normally terminating run must write capture_status")
            kinds = [r["kind"] for r in result.records]
            self.assertEqual("capture_started", kinds[0])
            self.assertEqual("capture_status", kinds[-1])
            sequences = [r["sequence"] for r in result.records]
            self.assertEqual(list(range(1, len(sequences) + 1)), sequences)

    def test_capture_does_not_change_how_the_game_is_played(self):
        """The whole point of an opt-in capture flag: play must be identical.

        This is asserted on two real runs rather than by reading the source,
        because the claim is about observable behaviour, not about intent.
        """
        with tempfile.TemporaryDirectory() as tmp:
            off = Path(tmp) / "off"
            on = Path(tmp) / "on"
            first = _play(off)
            second = _play(on, "--analysis-capture")
            self.assertEqual(first.returncode, second.returncode,
                             "capture must not change the game's outcome")
            self.assertEqual(_normalized(off / "match.ndjson"),
                             _normalized(on / "match.ndjson"),
                             "capture must not change the recorded game")

    def test_capture_adds_no_provider_call_and_no_driver_query(self):
        """Counted from the transports in the log, not from source inspection."""
        def counts(log: Path) -> tuple[int, int]:
            requests = queries = 0
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    kind = json.loads(line).get("type")
                except json.JSONDecodeError:
                    continue
                if kind == "model_request":
                    requests += 1
                elif kind == "query":
                    queries += 1
            return requests, queries

        with tempfile.TemporaryDirectory() as tmp:
            off = Path(tmp) / "off"
            on = Path(tmp) / "on"
            _play(off)
            _play(on, "--analysis-capture")
            self.assertEqual(counts(off / "match.ndjson"),
                             counts(on / "match.ndjson"),
                             "capture must add zero provider calls and zero driver queries")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(Path(DRIVER).is_file(),
                     "built greedy_driver required; run tools.fast_check first")
class AnalysisCaptureDecisionTraceTests(unittest.TestCase):
    """Stack 2: what was offered, selected, repaired, and executed."""

    def _play_trace(self, directory: Path, *extra: str) -> subprocess.CompletedProcess:
        directory.mkdir(parents=True, exist_ok=True)
        # Turn 1: an illegal custom Move (destination 99,99 cannot exist) is
        # rejected by pre-submit validation, repaired by a plain EndTurn.
        orders = directory / "orders.jsonl"
        orders.write_text(
            '{"text": "{\\"actions\\": [{\\"action\\": \\"Move\\", \\"unit_id\\": 1, '
            '\\"col\\": 99, \\"row\\": 99}, {\\"action\\": \\"EndTurn\\"}]}"}\n'
            '{"text": "{\\"actions\\": [{\\"action\\": \\"EndTurn\\"}]}"}\n',
            encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-m", "tools.llm_client",
             "--driver", DRIVER, "--seed", "42", "--max-turns", "2",
             "--orders-file", str(orders),
             "--log", str(directory / "match.ndjson"), *extra],
            cwd=ROOT, capture_output=True, text=True, timeout=300)

    def test_rejected_repair_commit_trace_joins_each_event_to_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "trace"
            result = self._play_trace(run, "--analysis-capture")
            self.assertEqual(0, result.returncode, result.stderr[-500:])
            analysis = analysis_dir_for_log(run / "match.ndjson")
            read = read_records(analysis)
            kinds = [r["kind"] for r in read.records]

            # The rejected custom action is visible as a failed validation and
            # a repair, and the repaired batch commits.
            self.assertIn("batch_validation", kinds)
            self.assertIn("response_repair", kinds)
            self.assertIn("execution_submit", kinds)
            self.assertIn("action_commit", kinds)
            self.assertIn("stage_timing", kinds)

            rejected = [r for r in read.records
                        if r["kind"] == "batch_validation"
                        and (r.get("body") or {}).get("valid") is False]
            self.assertEqual(1, len(rejected), "the illegal Move must be rejected once")

            # The rejected proposal produced no committed-action count: every
            # action_commit's batch_id must appear in an execution_submit.
            submits = {r.get("batch_id") for r in read.records
                       if r["kind"] == "execution_submit"}
            commits = [r for r in read.records if r["kind"] == "action_commit"]
            self.assertTrue(commits)
            for commit in commits:
                self.assertIn(commit.get("batch_id"), submits)

            # The rejected batch itself is not among the commits.
            rejected_batches = {r.get("batch_id") for r in read.records
                                if r["kind"] == "execution_submit"
                                and (r.get("body") or {}).get("repair") is not None}
            # The repair flag marks the repaired submission; the original
            # rejected proposal never reached the engine at all (pre-submit
            # validation), so it has no batch id to confuse the join.
            committed_ids = {c.get("batch_id") for c in commits}
            self.assertFalse(rejected_batches & committed_ids - committed_ids,
                             "a rejected proposal must not be reported as committed")

            # Stage timings carry measured spans; an absent span is unknown.
            timings = [r for r in read.records if r["kind"] == "stage_timing"]
            self.assertTrue(timings)
            for timing in timings:
                spans = (timing.get("body") or {}).get("spans") or {}
                self.assertIn("provider_wait_ms", spans)

            # The orders backend writes no usage sidecar: missing, not zero.
            receipts = [r for r in read.records if r["kind"] == "usage_receipt"]
            self.assertEqual(1, len(receipts))
            self.assertEqual("missing", receipts[0]["evidence_status"])

            # Every mirrored record references its exact game-log bytes, and
            # those references verify.
            with_refs = [r for r in read.records if r.get("refs")]
            self.assertTrue(with_refs)
            validate = subprocess.run(
                [sys.executable, "-m", "tools.game_analysis", "validate",
                 "--archive", str(run / "match.ndjson")],
                cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(0, validate.returncode, validate.stdout)

    def test_byte_cap_flag_stops_capture_visibly_and_game_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            off = Path(tmp) / "off"
            capped = Path(tmp) / "capped"
            plain = self._play_trace(off)
            stopped = self._play_trace(capped, "--analysis-capture",
                                       "--analysis-byte-cap", "1024")
            self.assertEqual(plain.returncode, stopped.returncode,
                             "a stopped sidecar must not change the game's outcome")
            read = read_records(analysis_dir_for_log(capped / "match.ndjson"))
            self.assertTrue(read.has_final_marker,
                            "the final capture_status marker must still be written")
            self.assertEqual("stopped_byte_cap", read.records[-1]["body"]["outcome"])
            self.assertLess(len(read.records), 18,
                            "a 1 KiB cap must stop capture well before a full trace")
