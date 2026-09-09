import unittest

from .model_usage import (
    CODEX_USAGE_MAP,
    FIREWORKS_USAGE_MAP,
    ModelCall,
    aggregate_calls,
    build_call,
    dedupe_calls,
    merge_lifecycle,
    normalize_int,
    normalize_usage,
    request_aggregate_from_legacy,
    source_identity,
    validate_call,
)


class NormalizeIntTests(unittest.TestCase):
    def test_clean_nonnegative_int_accepted(self):
        self.assertEqual(normalize_int(5881), (5881, None))
        self.assertEqual(normalize_int(0), (0, None))

    def test_none_is_unknown_not_zero(self):
        self.assertEqual(normalize_int(None), (None, None))

    def test_bool_rejected(self):
        value, gap = normalize_int(True)
        self.assertIsNone(value)
        self.assertIn("boolean_not_a_count", gap)

    def test_negative_rejected(self):
        value, gap = normalize_int(-3)
        self.assertIsNone(value)
        self.assertIn("negative_count", gap)

    def test_numeric_string_rejected(self):
        value, gap = normalize_int("42")
        self.assertIsNone(value)
        self.assertIn("numeric_string_not_a_count", gap)

    def test_float_rejected(self):
        value, gap = normalize_int(4.2)
        self.assertIsNone(value)
        self.assertIn("non_integer_count", gap)


class NormalizeUsageTests(unittest.TestCase):
    def test_fireworks_mapping(self):
        raw = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        normalized, gaps = normalize_usage(raw, FIREWORKS_USAGE_MAP)
        self.assertEqual(normalized["input_tokens"], 100)
        self.assertEqual(normalized["output_tokens"], 50)
        self.assertEqual(normalized["total_tokens"], 150)
        self.assertIsNone(normalized["reasoning_tokens"])
        self.assertEqual(gaps, [])

    def test_never_derives_total_from_parts(self):
        raw = {"prompt_tokens": 100, "completion_tokens": 50}  # no explicit total
        normalized, _ = normalize_usage(raw, FIREWORKS_USAGE_MAP)
        self.assertIsNone(normalized["total_tokens"])

    def test_malformed_field_reported_as_gap_not_zeroed(self):
        raw = {"prompt_tokens": "100", "completion_tokens": 50}
        normalized, gaps = normalize_usage(raw, FIREWORKS_USAGE_MAP)
        self.assertIsNone(normalized["input_tokens"])
        self.assertEqual(normalized["output_tokens"], 50)
        self.assertTrue(any("input_tokens" in g for g in gaps))

    def test_non_dict_usage_reports_gap(self):
        normalized, gaps = normalize_usage("not an object", FIREWORKS_USAGE_MAP)
        self.assertTrue(all(v is None for v in normalized.values()))
        self.assertTrue(gaps)

    def test_none_usage_no_gap(self):
        normalized, gaps = normalize_usage(None, FIREWORKS_USAGE_MAP)
        self.assertTrue(all(v is None for v in normalized.values()))
        self.assertEqual(gaps, [])

    def test_codex_mapping_includes_reasoning_subset(self):
        raw = {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 20,
               "reasoning_output_tokens": 5, "total_tokens": 30}
        normalized, gaps = normalize_usage(raw, CODEX_USAGE_MAP)
        self.assertEqual(normalized["reasoning_tokens"], 5)
        self.assertEqual(normalized["total_tokens"], 30)
        self.assertEqual(gaps, [])


class SourceIdentityTests(unittest.TestCase):
    def test_prefers_response_id(self):
        key = source_identity("fireworks", "thread-1", "resp-9", "attempt-1")
        self.assertIn("resp-9", key)

    def test_falls_back_to_attempt_id_when_response_unknown(self):
        key = source_identity("fireworks", "thread-1", None, "attempt-1")
        self.assertIn("attempt-1", key)

    def test_distinct_attempts_produce_distinct_identities(self):
        a = source_identity("fireworks", None, None, "attempt-1")
        b = source_identity("fireworks", None, None, "attempt-2")
        self.assertNotEqual(a, b)


class ModelCallValidationTests(unittest.TestCase):
    def test_missing_ids_rejected(self):
        problems = validate_call(ModelCall(game_id="", call_id=""))
        self.assertIn("missing_game_id", problems)
        self.assertIn("missing_call_id", problems)

    def test_valid_minimal_call(self):
        problems = validate_call(ModelCall(game_id="g1", call_id="c1"))
        self.assertEqual(problems, [])

    def test_unknown_status_rejected(self):
        problems = validate_call(ModelCall(game_id="g1", call_id="c1", status="bogus"))
        self.assertIn("unknown_status:'bogus'", problems)


class BuildCallTests(unittest.TestCase):
    def test_fake_provider_length_finish_reason_retains_exact_counts(self):
        """The Stack 1 headline acceptance case: input=5881, output=16384,
        reasoning=16384, total=22265, empty content, finish_reason=length."""
        raw = {"prompt_tokens": 5881, "completion_tokens": 16384,
               "reasoning_tokens": 16384, "total_tokens": 22265}
        mapping = dict(FIREWORKS_USAGE_MAP, reasoning_tokens="reasoning_tokens")
        call = build_call(game_id="g1", call_id="c1", provider="fireworks",
                           transport="fireworks_chat_completions", raw_usage=raw,
                           usage_map=mapping, status="failed", finish_reason="length")
        self.assertEqual(call.input_tokens, 5881)
        self.assertEqual(call.output_tokens, 16384)
        self.assertEqual(call.reasoning_tokens, 16384)
        self.assertEqual(call.total_tokens, 22265)
        self.assertEqual(call.finish_reason, "length")
        self.assertEqual(call.raw_usage_json, raw)
        self.assertEqual(validate_call(call), [])

    def test_unfamiliar_nested_field_preserved_in_raw_json(self):
        raw = {"prompt_tokens": 10, "completion_tokens": 5,
               "prompt_tokens_details": {"cached_tokens": 3, "audio_tokens": 0}}
        call = build_call(game_id="g1", call_id="c1", provider="fireworks", transport="t",
                           raw_usage=raw, usage_map=FIREWORKS_USAGE_MAP)
        self.assertEqual(call.raw_usage_json["prompt_tokens_details"], {"cached_tokens": 3, "audio_tokens": 0})


class MergeLifecycleTests(unittest.TestCase):
    def test_dispatch_then_completion_upserts(self):
        dispatched = ModelCall(game_id="g1", call_id="c1", status="dispatched", started_at="t0")
        completed = ModelCall(game_id="g1", call_id="c1", status="completed", ended_at="t1",
                               input_tokens=10, output_tokens=5)
        merged, conflicts = merge_lifecycle(dispatched, completed)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged.status, "completed")
        self.assertEqual(merged.started_at, "t0")
        self.assertEqual(merged.ended_at, "t1")
        self.assertEqual(merged.input_tokens, 10)

    def test_conflicting_final_usage_is_reported_not_overwritten(self):
        first = ModelCall(game_id="g1", call_id="c1", status="completed", input_tokens=10)
        second = ModelCall(game_id="g1", call_id="c1", status="completed", input_tokens=20)
        merged, conflicts = merge_lifecycle(first, second)
        self.assertEqual(conflicts, ["input_tokens:10!=20"])
        self.assertEqual(merged.input_tokens, 10)  # retained, not last-writer-wins
        self.assertTrue(any("conflict" in g for g in merged.normalization_gaps))

    def test_identical_repeated_value_is_not_a_conflict(self):
        first = ModelCall(game_id="g1", call_id="c1", input_tokens=10)
        second = ModelCall(game_id="g1", call_id="c1", input_tokens=10)
        _, conflicts = merge_lifecycle(first, second)
        self.assertEqual(conflicts, [])

    def test_mismatched_identity_raises(self):
        a = ModelCall(game_id="g1", call_id="c1")
        b = ModelCall(game_id="g1", call_id="c2")
        with self.assertRaises(ValueError):
            merge_lifecycle(a, b)


class DedupeCallsTests(unittest.TestCase):
    def test_retry_creates_two_calls(self):
        first = ModelCall(game_id="g1", call_id="c1", input_tokens=5)
        retry = ModelCall(game_id="g1", call_id="c2", retry_of_call_id="c1", input_tokens=7)
        deduped, conflicts = dedupe_calls([first, retry])
        self.assertEqual(len(deduped), 2)
        self.assertEqual(conflicts, {})

    def test_duplicate_notification_does_not_create_extra_call(self):
        first = ModelCall(game_id="g1", call_id="c1", status="dispatched")
        duplicate = ModelCall(game_id="g1", call_id="c1", status="completed", output_tokens=5)
        deduped, _ = dedupe_calls([first, duplicate])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].status, "completed")

    def test_same_prompt_hash_different_call_ids_both_kept(self):
        # Two paid retries of the identical prompt must never merge.
        a = ModelCall(game_id="g1", call_id="c1", source_hash="sameprompt")
        b = ModelCall(game_id="g1", call_id="c2", source_hash="sameprompt")
        deduped, _ = dedupe_calls([a, b])
        self.assertEqual(len(deduped), 2)


class AggregateCallsTests(unittest.TestCase):
    def test_fully_measured_group(self):
        calls = [ModelCall(game_id="g1", call_id=f"c{i}", input_tokens=10, output_tokens=5)
                 for i in range(3)]
        agg = aggregate_calls(calls)
        self.assertEqual(agg["input_tokens"]["sum"], 30)
        self.assertTrue(agg["input_tokens"]["fully_measured"])
        self.assertIsNone(agg["reasoning_tokens"]["sum"])
        self.assertFalse(agg["reasoning_tokens"]["fully_measured"])

    def test_partial_group_labels_partial_sum(self):
        calls = [ModelCall(game_id="g1", call_id="c1", input_tokens=10),
                 ModelCall(game_id="g1", call_id="c2", input_tokens=None)]
        agg = aggregate_calls(calls)
        self.assertEqual(agg["input_tokens"]["sum"], 10)
        self.assertFalse(agg["input_tokens"]["fully_measured"])
        self.assertEqual(agg["input_tokens"]["unknown_calls"], 1)

    def test_never_derives_total_from_summed_parts(self):
        calls = [ModelCall(game_id="g1", call_id="c1", input_tokens=10, output_tokens=5, total_tokens=None)]
        agg = aggregate_calls(calls)
        self.assertIsNone(agg["total_tokens"]["sum"])

    def test_empty_group(self):
        agg = aggregate_calls([])
        self.assertEqual(agg["call_count"], 0)
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            self.assertIsNone(agg[field]["sum"])
            self.assertFalse(agg[field]["fully_measured"])


class RequestAggregateFromLegacyTests(unittest.TestCase):
    def test_labels_as_request_aggregate(self):
        legacy = {"input_tokens": 100, "output_tokens": 50}
        wrapped = request_aggregate_from_legacy(legacy)
        self.assertEqual(wrapped["kind"], "request_aggregate")
        self.assertEqual(wrapped["tokens"]["input_tokens"], 100)
        self.assertEqual(wrapped["tokens"]["output_tokens"], 50)
        self.assertIsNone(wrapped["tokens"]["reasoning_tokens"])

    def test_malformed_legacy_field_reported_not_zeroed(self):
        wrapped = request_aggregate_from_legacy({"input_tokens": True})
        self.assertIsNone(wrapped["tokens"]["input_tokens"])
        self.assertTrue(wrapped["normalization_gaps"])

    def test_missing_usage_is_all_unknown(self):
        wrapped = request_aggregate_from_legacy(None)
        self.assertTrue(all(v is None for v in wrapped["tokens"].values()))


if __name__ == "__main__":
    unittest.main()
