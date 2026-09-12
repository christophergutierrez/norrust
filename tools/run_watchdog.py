#!/usr/bin/env python3
"""Bounded, recording-only progress projection for one Norrust run.

The watchdog reads the maintained match log and provider evidence as they are
appended.  It does not call a model and it never interprets player text as an
instruction.  Evidence is exposed only through byte ranges recorded in the
watchdog index, which makes a later append or replacement detectable.
"""
from __future__ import annotations

import argparse
import base64
import collections
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable


MAX_EVIDENCE_READ = 2048
MAX_INDEXED_RECORDS = 512
MAX_STATUS_ITEMS = 8
MAX_RECENT_ERRORS = 8
MAX_PARSER_BUFFER = 64 * 1024
DEFAULT_POLL_INTERVAL = 5.0
REGULAR_INTERVAL = 300.0
ALERT_COOLDOWN = 60.0

_RUNS: dict[str, "RunWatchdog"] = {}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _safe_text(value: Any, limit: int = 256) -> str:
    text = str(value) if value is not None else ""
    text = re.sub(r"(?i)(authorization|api[_ -]?key|bearer|token)(\s*[:=]\s*)\S+",
                  r"\1\2[redacted]", text)
    return text[:limit]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wall_now() -> float:
    return time.time()


def _parse_wall(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _decode_stream_chunk(raw: bytes) -> str:
    """Return model content/reasoning from one recorded chunks.ndjson line."""
    try:
        value = json.loads(raw)
        payload = base64.b64decode(value.get("data_b64", ""), validate=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    parser = _SSEContentParser(max(MAX_PARSER_BUFFER, len(payload) + 1))
    text, _error = parser.feed(payload)
    if text:
        return text
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    output: list[str] = []
    for match in re.finditer(r'"(?:content|reasoning_content|reasoning)"\s*:\s*"((?:\\.|[^"\\])*)"', decoded):
        try:
            output.append(json.loads('"' + match.group(1) + '"'))
        except json.JSONDecodeError:
            continue
    return "".join(output)


class RepetitionDetector:
    """Find exact repeated meaningful passages in a bounded stream tail.

    A passage must contain at least ``min_passage`` characters and 24
    alphanumeric characters.  This excludes JSON punctuation and short tool
    boilerplate while keeping the detector deterministic and cheap.
    """

    def __init__(self, min_passage: int = 64, window: int = 4096,
                 max_alerts: int = 32) -> None:
        if min_passage < 16 or window < min_passage * 2:
            raise ValueError("repetition window must hold two minimum passages")
        self.min_passage = min_passage
        self.window = window
        self.max_alerts = max_alerts
        self._tail = ""
        self.counts: collections.Counter[str] = collections.Counter()
        self.alerts: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    @staticmethod
    def _meaningful(passage: str) -> bool:
        alnum = sum(character.isalnum() for character in passage)
        punctuation = sum(not character.isalnum() and not character.isspace()
                          for character in passage)
        return alnum >= 24 and alnum > punctuation

    def feed(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        previous = self._tail
        combined = previous + text
        new_alerts: list[dict[str, Any]] = []
        # Only inspect a suffix-sized set of passages.  The previous tail is
        # bounded, so this never scans an accumulated stream.
        minimum = self.min_passage
        for length in (minimum, min(self.window // 2, minimum * 2), self.window // 2):
            if length > len(combined):
                continue
            passage = combined[-length:]
            if not self._meaningful(passage):
                continue
            start = max(0, len(previous) - self.window)
            if passage not in previous[start:]:
                continue
            key = _digest(passage.encode("utf-8"))
            self.counts[key] += 1
            if key not in self._seen:
                if len(self._seen) >= self.max_alerts:
                    continue
                self._seen.add(key)
                alert = {"kind": "repeated_stream_passage", "identity": key,
                         "count": self.counts[key], "characters": length,
                         "excerpt": _safe_text(passage, 160)}
                self.alerts.append(alert)
                self.alerts = self.alerts[-self.max_alerts:]
                new_alerts.append(alert)
            if len(self.counts) > self.max_alerts * 2:
                oldest = next(iter(self.counts))
                del self.counts[oldest]
            break
        self._tail = combined[-self.window:]
        return new_alerts


class _NDJSONCursor:
    """Incremental byte cursor retaining only one bounded incomplete line."""

    def __init__(self, offset: int = 0, buffer: bytes = b"", buffer_start: int | None = None):
        self.offset = offset
        self.buffer = buffer
        self.buffer_start = offset if buffer_start is None else buffer_start

    def read(self, path: Path, max_bytes: int = 64 * 1024) -> tuple[list[tuple[int, int, bytes]], list[str]]:
        records: list[tuple[int, int, bytes]] = []
        errors: list[str] = []
        try:
            size = path.stat().st_size
        except OSError as exc:
            return records, [f"unavailable:{exc}"]
        if size < self.offset:
            errors.append("truncated")
            self.offset = 0
            self.buffer = b""
            self.buffer_start = 0
        try:
            with path.open("rb") as stream:
                stream.seek(self.offset)
                while True:
                    chunk = stream.read(max_bytes)
                    if not chunk:
                        break
                    self.offset += len(chunk)
                    self.buffer += chunk
                    while b"\n" in self.buffer:
                        line, self.buffer = self.buffer.split(b"\n", 1)
                        start = self.buffer_start
                        end = start + len(line) + 1
                        self.buffer_start = end
                        records.append((start, end, line + b"\n"))
                    if len(self.buffer) > max_bytes:
                        # Preserve a raw range before discarding the prefix;
                        # callers index it as an incomplete/degraded record.
                        discard = len(self.buffer) - max_bytes
                        records.append((self.buffer_start, self.buffer_start + discard,
                                        self.buffer[:discard]))
                        errors.append(f"buffer_exceeded:{discard}")
                        self.buffer_start += discard
                        self.buffer = self.buffer[discard:]
        except OSError as exc:
            errors.append(f"read_error:{exc}")
        return records, errors


class EvidenceError(ValueError):
    """The requested evidence is not a valid immutable run-owned range."""


class _SSEContentParser:
    """Parse Fireworks SSE bytes and return content/reasoning deltas only."""

    def __init__(self, limit: int = MAX_PARSER_BUFFER):
        import codecs
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.pending = ""
        self.limit = limit

    def feed(self, raw: bytes) -> tuple[str, str | None]:
        try:
            self.pending += self.decoder.decode(raw, final=False)
        except UnicodeDecodeError:
            return "", "invalid_utf8"
        if len(self.pending) > self.limit:
            self.pending = self.pending[-self.limit:]
            return "", "sse_buffer_exceeded"
        # Test providers and simple local recording fixtures may contain raw
        # text rather than SSE. Keep that fallback bounded; actual SSE frames
        # are reduced to model deltas below.
        if "data:" not in self.pending and "\n\n" not in self.pending:
            if len(self.pending) >= 64:
                text, self.pending = self.pending, ""
                return text, None
            return "", None
        output: list[str] = []
        while True:
            match = re.search(r"\r?\n\r?\n", self.pending)
            if match is None:
                break
            frame, self.pending = self.pending[:match.start()], self.pending[match.end():]
            data: list[str] = []
            for line in frame.splitlines():
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
            if not data:
                continue
            payload = "\n".join(data)
            if payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except (TypeError, ValueError):
                return "", "invalid_sse_json"
            if not isinstance(event, dict):
                continue
            for choice in event.get("choices", []):
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta", {})
                if isinstance(delta, dict):
                    for key in ("content", "reasoning_content", "reasoning"):
                        if isinstance(delta.get(key), str):
                            output.append(delta[key])
        return "".join(output), None


class RunWatchdog:
    """Incrementally record and project one run's bounded status."""

    def __init__(self, log_path: str | os.PathLike[str], run_id: str | None = None,
                 evidence_dir: str | os.PathLike[str] | None = None,
                 *, clock: Callable[[], float] = time.monotonic,
                 poll_interval: float = DEFAULT_POLL_INTERVAL,
                 regular_interval: float = REGULAR_INTERVAL,
                 cooldown: float = ALERT_COOLDOWN,
                 parser_buffer: int = MAX_PARSER_BUFFER) -> None:
        self.log_path = Path(log_path).resolve()
        if not self.log_path.name or self.log_path.parent == self.log_path:
            raise ValueError("log_path must identify a file")
        self.root = self.log_path.parent
        # Persist identity independently of the common log basename. Two
        # isolated games both called match.ndjson must never share a registry ID.
        saved_identity = self.root / f"{self.log_path.stem}.watchdog" / "state.json"
        existing_id = None
        if saved_identity.exists():
            saved = json.loads(saved_identity.read_text(encoding="utf-8"))
            existing_id = saved.get("run_id")
            if not isinstance(existing_id, str) or not existing_id:
                raise EvidenceError("invalid persisted watchdog identity")
            if run_id is not None and run_id != existing_id:
                raise EvidenceError("watchdog identity conflicts with existing run")
        self.run_id = run_id or existing_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.run_id):
            raise ValueError("run_id contains unsupported characters")
        self.watchdog_dir = self.root / f"{self.log_path.stem}.watchdog"
        self.watchdog_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir = Path(evidence_dir).resolve() if evidence_dir else (
            self.root / f"{self.log_path.stem}.evidence")
        if not self._inside(self.evidence_dir, self.root):
            raise ValueError("evidence_dir must be under the log parent")
        self.clock = clock
        self.poll_interval = max(0.0, float(poll_interval))
        self.regular_interval = max(0.0, float(regular_interval))
        self.cooldown = max(0.0, float(cooldown))
        self.parser_buffer = max(1024, int(parser_buffer))
        self.state_path = self.watchdog_dir / "state.json"
        self.index_path = self.watchdog_dir / "index.ndjson"
        self.journal_path = self.watchdog_dir / "journal.ndjson"
        self._index: dict[str, dict[str, Any]] = {}
        self._cursors: dict[str, _NDJSONCursor] = {}
        self._records: collections.deque[dict[str, Any]] = collections.deque(maxlen=MAX_INDEXED_RECORDS)
        self._latest: dict[str, Any] = {}
        self._alerts: list[dict[str, Any]] = []
        self._alert_seen: set[str] = set()
        self._rejected: collections.Counter[str] = collections.Counter()
        self._tool_requests: collections.Counter[str] = collections.Counter()
        self._repetition = RepetitionDetector()
        self._stream_parsers: dict[str, _SSEContentParser] = {}
        self._detectors: dict[str, RepetitionDetector] = {}
        self._sequence = 0
        self._last_poll: float | None = None
        self._last_progress: float | None = None
        self._last_record: float | None = None
        self._last_stream: float | None = None
        self._last_regular: float | None = None
        self._next_poll = 0.0
        self._stream_bytes = 0
        self._usage_final = 0
        self._usage_measured = 0
        self._usage_unknown = 0
        self._usage_calls: dict[str, dict[str, Any]] = {}
        self._previous_gold: list[Any] | None = None
        self._degraded: list[str] = []
        self._loaded = False
        self._load_state()
        _RUNS[self.run_id] = self

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _load_state(self) -> None:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("run_id") != self.run_id:
                return
            self._sequence = int(raw.get("observation_sequence", 0))
            self._stream_bytes = int(raw.get("received_stream_bytes", 0))
            self._last_regular = raw.get("last_regular_monotonic")
            self._last_progress = raw.get("last_progress_monotonic")
            self._last_record = raw.get("last_record_monotonic")
            self._last_stream = raw.get("last_stream_monotonic")
            latest = raw.get("latest")
            if isinstance(latest, dict):
                self._latest.update(latest)
            self._usage_final = int(raw.get("usage_final", 0))
            self._usage_measured = int(raw.get("usage_measured", 0))
            self._usage_unknown = int(raw.get("usage_unknown", 0))
            self._usage_calls = raw.get("usage_calls", {})
            for item in raw.get("alerts", []):
                if isinstance(item, dict):
                    self._alerts.append(item)
                    identity = item.get("identity")
                    if isinstance(identity, str):
                        self._alert_seen.add(identity)
            for item in raw.get("index", []):
                if isinstance(item, dict) and isinstance(item.get("evidence_id"), str):
                    self._index[item["evidence_id"]] = item
            cursors = raw.get("cursors", {})
            if isinstance(cursors, dict):
                for key, value in cursors.items():
                    if isinstance(value, dict):
                        self._cursors[key] = _NDJSONCursor(
                            int(value.get("offset", 0)),
                            base64.b64decode(value.get("buffer", "")),
                            int(value.get("buffer_start", value.get("offset", 0))))
            self._loaded = True
        except FileNotFoundError:
            pass  # A new recorder has no persisted state yet.
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._degraded.append(f"state_unavailable:{type(exc).__name__}")

    def _save_state(self) -> None:
        state = {
            "version": 1, "run_id": self.run_id,
            "log_path": self.log_path.name,
            "observation_sequence": self._sequence,
            "received_stream_bytes": self._stream_bytes,
            "last_regular_monotonic": self._last_regular,
            "last_progress_monotonic": self._last_progress,
            "last_record_monotonic": self._last_record,
            "last_stream_monotonic": self._last_stream,
            "latest": self._latest,
            "usage_final": self._usage_final,
            "usage_measured": self._usage_measured,
            "usage_unknown": self._usage_unknown,
            "usage_calls": self._usage_calls,
            "alerts": self._alerts[-32:],
            "index": list(self._index.values())[-MAX_INDEXED_RECORDS:],
            "cursors": {key: {"offset": value.offset,
                              "buffer_start": value.buffer_start,
                              "buffer": base64.b64encode(value.buffer).decode("ascii")}
                        for key, value in self._cursors.items()},
        }
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        temporary.write_text(_json(state) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _append_journal(self, value: dict[str, Any]) -> None:
        try:
            with self.journal_path.open("a", encoding="utf-8") as stream:
                stream.write(_json(value) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            self._degraded.append(f"journal_write_failed:{type(exc).__name__}")

    def _index_range(self, relative: str, start: int, end: int, raw: bytes,
                     *, kind: str = "raw", record_type: str | None = None) -> str:
        identity = f"{relative}:{start}:{end}:{_digest(raw)}"
        evidence_id = "log:" + identity.split(":", 1)[1] if relative == self.log_path.name else (
            "artifact:" + _digest(identity.encode())[:24])
        entry = {"evidence_id": evidence_id, "run_id": self.run_id,
                 "artifact": relative, "start": start, "end": end,
                 "sha256": _digest(raw), "kind": kind}
        if record_type:
            entry["record_type"] = record_type
        self._index[evidence_id] = entry
        if len(self._index) > MAX_INDEXED_RECORDS:
            self._index.pop(next(iter(self._index)))
        try:
            with self.index_path.open("a", encoding="utf-8") as stream:
                stream.write(_json(entry) + "\n")
        except OSError as exc:
            self._degraded.append(f"index_write_failed:{type(exc).__name__}")
        return evidence_id

    def _lookup_index(self, evidence_id: str) -> dict[str, Any] | None:
        entry = self._index.get(evidence_id)
        if entry is not None:
            return entry
        # Older ranges remain durable in the append-only index even after the
        # bounded in-memory lookup window has rotated them out.
        try:
            with self.index_path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict) and value.get("evidence_id") == evidence_id:
                        return value
        except OSError:
            return None
        return None

    def _record_error(self, reason: str) -> None:
        if reason in self._degraded:
            return
        self._degraded.append(reason)
        self._append_journal({"type": "coverage", "reason": reason,
                              "at": _wall_now()})

    def _scan_log(self, now: float) -> None:
        key = self.log_path.name
        cursor = self._cursors.setdefault(key, _NDJSONCursor())
        if not self.log_path.exists() and cursor.offset == 0:
            return  # Supervisor has not launched the client yet.
        records, errors = cursor.read(self.log_path, self.parser_buffer)
        for error in errors:
            self._record_error(f"log_{error}")
        for start, end, raw in records:
            evidence_id = self._index_range(key, start, end, raw, kind="record")
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._record_error("log_invalid_record")
                continue
            if not isinstance(value, dict):
                self._record_error("log_record_not_object")
                continue
            value = dict(value)
            value["_evidence_id"] = evidence_id
            self._records.append(value)
            self._observe_record(value, now)
        if not self.log_path.exists() and cursor.offset:
            self._record_error("log_missing")

    def _scan_ndjson_artifact(self, path: Path, relative: str, now: float,
                              *, stream_chunks: bool = False) -> None:
        cursor = self._cursors.setdefault(relative, _NDJSONCursor())
        records, errors = cursor.read(path, self.parser_buffer)
        for error in errors:
            self._record_error(f"{relative}:{error}")
        for start, end, raw in records:
            evidence_id = self._index_range(relative, start, end, raw, kind="record")
            if relative == "usage.ndjson":
                try:
                    value = json.loads(raw)
                    # The shared usage sidecar contains player and observer
                    # lifecycles. Recorder health is player progress; keep
                    # observer calls for catalog role accounting but do not
                    # count them as player usage here.
                    if (isinstance(value, dict) and value.get("call_role") != "observer"
                            and isinstance(value.get("call_id"), str)):
                        key = value["call_id"]
                        if key in self._usage_calls or len(self._usage_calls) < MAX_INDEXED_RECORDS:
                            fields = ("input_tokens", "output_tokens", "reasoning_tokens",
                                      "cached_input_tokens", "cache_write_input_tokens", "total_tokens")
                            tokens = {field: value.get(field) if type(value.get(field)) is int
                                      and value[field] >= 0 else None for field in fields}
                            if value.get("record_kind") == "final" or key not in self._usage_calls:
                                self._usage_calls[key] = dict(tokens, final=value.get("record_kind") == "final")
                            self._usage_final = sum(row["final"] for row in self._usage_calls.values())
                            self._usage_measured = sum(row["total_tokens"] is not None for row in self._usage_calls.values())
                            self._usage_unknown = len(self._usage_calls) - self._usage_measured
                        else:
                            self._record_error("usage_call_index_overflow")
                except (ValueError, TypeError, json.JSONDecodeError):
                    self._record_error("usage_invalid_record")
            if not stream_chunks:
                continue
            try:
                value = json.loads(raw)
                data = base64.b64decode(value.get("data_b64", ""), validate=True)
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                self._record_error(f"{relative}:invalid_chunk")
                continue
            self._stream_bytes += len(data)
            self._last_stream = now
            parser = self._stream_parsers.setdefault(relative, _SSEContentParser(self.parser_buffer))
            detector = self._detectors.setdefault(relative, RepetitionDetector())
            text, parser_error = parser.feed(data)
            if parser_error:
                self._record_error(f"{relative}:{parser_error}")
            for alert in detector.feed(text):
                self._repetition.counts[alert["identity"]] = detector.counts[alert["identity"]]
                self._raise_alert(alert, now)

    def _scan_artifacts(self, now: float) -> None:
        # Usage is authoritative when present. A missing sidecar is explicitly
        # unknown; bytes received from a stream never become token usage.
        usage = self.root / "usage.ndjson"
        if usage.is_file() and not usage.is_symlink():
            self._scan_ndjson_artifact(usage, usage.name, now)
        # Missing receipts are unknown usage, not a broken progress recorder.
        checkpoint_dir = self.log_path.with_suffix(".ckpt")
        if checkpoint_dir.is_dir() and not checkpoint_dir.is_symlink():
            for path in sorted(checkpoint_dir.glob("*.json")):
                if path.is_symlink():
                    self._record_error(f"{path.relative_to(self.root).as_posix()}:symlink")
                    continue
                self._scan_static(path, path.relative_to(self.root).as_posix())
        if self.evidence_dir.is_dir() and not self.evidence_dir.is_symlink():
            try:
                paths = sorted(path for path in self.evidence_dir.rglob("*")
                               if path.is_file() and not path.is_symlink())
            except OSError as exc:
                self._record_error(f"evidence_discovery:{type(exc).__name__}")
                paths = []
            for path in paths:
                relative = path.relative_to(self.root).as_posix()
                if path.name == "chunks.ndjson":
                    self._scan_ndjson_artifact(path, relative, now, stream_chunks=True)
                elif path.suffix == ".ndjson":
                    self._scan_ndjson_artifact(path, relative, now)
                else:
                    self._scan_static(path, relative)

    def _scan_static(self, path: Path, relative: str) -> None:
        if relative in self._cursors:
            return
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_PARSER_BUFFER * 16 + 1)
        except OSError as exc:
            self._record_error(f"{relative}:unavailable")
            return
        if len(raw) > MAX_PARSER_BUFFER * 16:
            # Keep an indexable prefix while explicitly labelling the omitted
            # data. Evidence readers can only expose this recorded prefix.
            self._record_error(f"{relative}:oversized")
            raw = raw[:MAX_PARSER_BUFFER * 16]
        self._index_range(relative, 0, len(raw), raw, kind="artifact")
        self._cursors[relative] = _NDJSONCursor(len(raw))

    def _observe_record(self, record: dict[str, Any], now: float) -> None:
        record_type = record.get("type")
        self._latest["type"] = record_type
        self._last_record = now
        if record_type in {"checkpoint_ref", "batch_committed", "turn_boundary",
                           "terminal", "game_end"}:
            self._last_progress = now
        if record_type == "driver" and isinstance(record.get("line"), dict):
            line = record["line"]
            if line.get("type") == "state":
                self._latest["revision"] = line.get("state_revision")
                self._latest["turn"] = line.get("turn")
                self._last_progress = now
                if isinstance(line.get("gold"), list):
                    if self._previous_gold is not None:
                        self._latest["objective_resource_deltas"] = {
                            "gold": [
                                (current - previous if isinstance(current, (int, float)) and isinstance(previous, (int, float)) else None)
                                for current, previous in zip(line["gold"], self._previous_gold)
                            ]}
                    self._previous_gold = list(line["gold"])
        elif record_type in {"checkpoint_ref", "batch_committed"}:
            if record.get("state_revision") is not None:
                self._latest["revision"] = record.get("state_revision")
            if record_type == "batch_committed":
                self._latest["committed_action"] = {
                    "batch_id": record.get("batch_id"),
                    "revision": record.get("state_revision"),
                    "evidence_id": record.get("_evidence_id"),
                }
        elif record_type == "turn_boundary":
            self._latest["last_completed_turn"] = record.get("side_turn_id", record.get("turn"))
        elif record_type == "forwarded_orders":
            self._latest["proposed_action"] = {
                "batch_id": record.get("batch_id"),
                "orders": record.get("orders", [])[:MAX_STATUS_ITEMS]
                if isinstance(record.get("orders"), list) else [],
                "revision": record.get("state_revision"),
                "evidence_id": record.get("_evidence_id"),
            }
        elif record_type in {"action_failure", "batch_validation"}:
            if record_type == "batch_validation" and record.get("valid") is not False:
                return
            revision = record.get("state_revision", record.get("revision"))
            if revision is None:
                revision = self._latest.get("revision")
            if revision is None:
                return
            signature = _digest(_json({"type": record_type,
                                       "failure": record.get("driver_failure", record.get("error")),
                                       "orders": record.get("orders"), "revision": revision}).encode())
            self._rejected[signature] += 1
            if self._rejected[signature] >= 3:
                self._raise_alert({"kind": "repeated_rejected_action", "identity": signature,
                                   "count": self._rejected[signature], "revision": revision}, now)
        elif record_type in {"model", "model_request", "tool_result", "query", "inspection",
                             "draft_review", "draft_review_inspection", "handoff_review"}:
            self._latest["activity"] = record_type
            if record_type == "tool_result":
                revision = self._latest.get("revision")
                request = record.get("request")
                if revision is not None and isinstance(request, dict):
                    signature = _digest(_json({"tool": record.get("tool"),
                                               "request": request, "revision": revision}).encode())
                    self._tool_requests[signature] += 1
                    if len(self._tool_requests) > 64:
                        del self._tool_requests[next(iter(self._tool_requests))]
                    if self._tool_requests[signature] >= 3:
                        self._raise_alert({"kind": "repeated_tool_request",
                                           "identity": signature,
                                           "count": self._tool_requests[signature],
                                           "revision": revision,
                                           "tool": record.get("tool")}, now)
        if record_type == "model_request":
            request_id = record.get("request_id")
            if record.get("status") in {"completed", "failed"}:
                self._latest["completed_request_id"] = request_id
        if record_type in {"terminal", "game_end", "budget_interrupted"}:
            self._latest["stage"] = "terminal"
        elif record_type in {"model_request", "model", "query", "tool_result"}:
            self._latest["stage"] = "request"
        elif record_type in {"side_turn_started", "turn_progress", "turn_boundary"}:
            self._latest["stage"] = "turn"
        elif record_type == "metadata":
            self._latest["stage"] = "starting"
            self._latest["conversation_id"] = record.get("conversation_id")
            self._latest["source_commit"] = record.get("source_commit")

    def _raise_alert(self, alert: dict[str, Any], now: float) -> None:
        identity = str(alert.get("identity") or _digest(_json(alert).encode()))
        if identity in self._alert_seen:
            return
        self._alert_seen.add(identity)
        if self._alerts and now - float(self._alerts[-1].get("monotonic", now)) < self.cooldown:
            alert = dict(alert)
            alert["coalesced"] = True
        alert = dict(alert, identity=identity, monotonic=now, observed_at=_wall_now())
        self._alerts.append(alert)
        self._alerts = self._alerts[-32:]
        self._append_journal({"type": "alert", **alert})

    def poll(self, *, force: bool = False) -> dict[str, Any]:
        now = float(self.clock())
        if not force and now < self._next_poll and self._last_poll is not None:
            return self.status()
        self._last_poll = now
        self._next_poll = now + self.poll_interval
        before_alerts = len(self._alerts)
        self._scan_log(now)
        self._scan_artifacts(now)
        regular = False
        active = self._latest.get("stage") != "terminal"
        if active and self._last_regular is None:
            self._last_regular = now
        elif active and self._last_regular is not None and now - self._last_regular >= self.regular_interval:
            regular = True
            self._last_regular = now
        self._sequence += 1
        packet = self._make_status(now, regular)
        if len(self._degraded) > 32:
            self._degraded = self._degraded[-32:]
        self._append_journal({"type": "status", "sequence": self._sequence,
                              "status": packet, "new_alerts": len(self._alerts) - before_alerts})
        self._latest["packet"] = packet
        try:
            self._save_state()
        except OSError as exc:
            self._record_error(f"state_write_failed:{type(exc).__name__}")
        self._latest["packet"] = packet
        return packet

    def _make_status(self, now: float, regular: bool = False) -> dict[str, Any]:
        request_age = None
        current_request = None
        context = self.root / "request_context.json"
        if context.is_file() and not context.is_symlink():
            try:
                with context.open("rb") as handle:
                    value = json.loads(handle.read(MAX_PARSER_BUFFER + 1))
                started = _parse_wall(value.get("dispatched_at")) if isinstance(value, dict) else None
                if started is not None:
                    request_age = max(0.0, _wall_now() - started)
                if isinstance(value, dict):
                    current_request = {key: value.get(key) for key in
                                       ("conversation_id", "harness_request_id", "request_sequence", "side_turn_id",
                                        "side", "state_revision", "requested_model", "purpose", "dispatched_at")
                                      if value.get(key) is not None}
                    if value.get("harness_request_id") == self._latest.get("completed_request_id"):
                        current_request = None
                        request_age = None
            except (OSError, ValueError, TypeError):
                self._record_error("request_context_invalid")
        if request_age is None:
            for record in reversed(self._records):
                if record.get("type") == "model_request" and record.get("status") == "started":
                    started = _parse_wall(record.get("started_at"))
                    if started is not None:
                        request_age = max(0.0, _wall_now() - started)
                    break
        if self._latest.get("stage") == "terminal":
            current_request = None
            request_age = None
        elif current_request is not None:
            self._latest["stage"] = "request"
        if self._last_progress is None:
            freshness_state = "unknown"
            since_progress = None
        else:
            since_progress = max(0.0, now - self._last_progress)
            freshness_state = "fresh" if since_progress < self.regular_interval else "stale"
        stage = self._latest.get("stage", "unknown")
        usage_path = self.root / "usage.ndjson"
        if self._usage_final == 0:
            usage = "unknown"
        elif self._usage_measured == len(self._usage_calls):
            usage = "measured"
        else:
            usage = "partial_unknown"
        recent_actions = []
        recent_errors = []
        for record in reversed(self._records):
            if record.get("type") in {"forwarded_orders", "batch_committed", "turn_boundary"} and len(recent_actions) < MAX_STATUS_ITEMS:
                recent_actions.append({"type": record.get("type"), "revision": record.get("state_revision"),
                                       "evidence_id": record.get("_evidence_id")})
            if record.get("type") in {"action_failure", "model_error", "query_error", "checkpoint_error"} and len(recent_errors) < MAX_RECENT_ERRORS:
                recent_errors.append({"type": record.get("type"), "code": record.get("code", record.get("error_code")),
                                      "message": _safe_text(record.get("message", record.get("error"))),
                                      "evidence_id": record.get("_evidence_id")})
        packet: dict[str, Any] = {
            "run_id": self.run_id,
            "observation_sequence": self._sequence,
            "conversation_id": self._latest.get("conversation_id") or (current_request or {}).get("conversation_id"),
            "stage": stage,
            "request_age_seconds": request_age,
            "current_request": current_request,
            "request_id": (current_request or {}).get("harness_request_id")
                if isinstance(current_request, dict) else None,
            "last_completed_turn": self._latest.get("last_completed_turn"),
            "committed_action": self._latest.get("committed_action"),
            "proposed_action": self._latest.get("proposed_action"),
            "revision": self._latest.get("revision"),
            "recent_actions": list(reversed(recent_actions)),
            "recent_errors": list(reversed(recent_errors)),
            "repetition": {"alerts": self._repetition.alerts[-MAX_STATUS_ITEMS:],
                            "counts": dict(self._repetition.counts)},
            "objective_resource_deltas": self._latest.get("objective_resource_deltas"),
            "received_stream_bytes": self._stream_bytes,
            "usage_coverage": {"status": usage, "source": usage_path.name,
                               "final_records": self._usage_final,
                               "measured_records": self._usage_measured,
                               "unknown_records": self._usage_unknown,
                               "call_count": len(self._usage_calls),
                               "measured_total_tokens": sum(row["total_tokens"] for row in self._usage_calls.values()
                                                            if row["total_tokens"] is not None)
                                                        if self._usage_measured else None},
            "freshness": {"state": freshness_state,
                          "seconds_since_progress": since_progress,
                          "seconds_since_record": (None if self._last_record is None else max(0.0, now - self._last_record)),
                          "seconds_since_stream": (None if self._last_stream is None else max(0.0, now - self._last_stream))},
            "alerts": self._alerts[-MAX_STATUS_ITEMS:],
            "regular_check_eligible": bool(regular),
            "previous_verdict": self._latest.get("previous_verdict"),
            "degraded": bool(self._degraded),
            "coverage_events": self._degraded[-MAX_RECENT_ERRORS:],
            "evidence_ids": list(self._index)[-MAX_STATUS_ITEMS:],
        }
        return packet

    def status(self) -> dict[str, Any]:
        packet = self._latest.get("packet")
        return dict(packet) if isinstance(packet, dict) else self._make_status(float(self.clock()), False)

    @property
    def run_directory(self) -> Path:
        return self.watchdog_dir

    def read_evidence(self, evidence_id: str, offset: int = 0,
                      limit: int = MAX_EVIDENCE_READ) -> dict[str, Any]:
        if not isinstance(evidence_id, str):
            raise EvidenceError("unknown evidence reference")
        if not isinstance(offset, int) or not isinstance(limit, int) or offset < 0:
            raise EvidenceError("offset and limit must be non-negative integers")
        if limit <= 0 or limit > MAX_EVIDENCE_READ:
            raise EvidenceError(f"limit must be between 1 and {MAX_EVIDENCE_READ}")
        entry = self._lookup_index(evidence_id)
        if entry is None:
            raise EvidenceError("unknown evidence reference")
        if entry.get("run_id") != self.run_id:
            raise EvidenceError("foreign run evidence")
        relative = entry.get("artifact")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise EvidenceError("invalid evidence path")
        path = self.root / relative
        resolved = path.resolve()
        if not self._inside(resolved, self.root) or path.is_symlink():
            raise EvidenceError("evidence path escapes run")
        start = int(entry["start"])
        end = int(entry["end"])
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                raw = stream.read(end - start)
        except OSError as exc:
            raise EvidenceError("evidence is unavailable") from exc
        if _digest(raw) != entry.get("sha256"):
            raise EvidenceError("evidence range changed")
        selected = raw[offset:offset + limit]
        truncated = offset + len(selected) < len(raw)
        if isinstance(relative, str) and relative.endswith("chunks.ndjson"):
            decoded_stream = _decode_stream_chunk(raw)
            if decoded_stream:
                bounded = decoded_stream[:limit]
                return {"run_id": self.run_id, "evidence_id": evidence_id,
                        "artifact": relative, "offset": offset, "limit": limit,
                        "bytes_read": len(bounded.encode("utf-8")),
                        "raw_bytes_read": len(selected), "raw_bytes": len(raw),
                        "truncated": len(decoded_stream) > len(bounded) or truncated,
                        "data": bounded, "data_b64": None,
                        "source_sha256": entry.get("sha256"),
                        "derived": "stream_content_reasoning"}
        try:
            data: str | None = selected.decode("utf-8")
            data_b64 = None
        except UnicodeDecodeError:
            data = None
            data_b64 = base64.b64encode(selected).decode("ascii")
        return {"run_id": self.run_id, "evidence_id": evidence_id,
                "artifact": relative, "offset": offset, "limit": limit,
                "bytes_read": len(selected), "truncated": truncated,
                "data": data, "data_b64": data_b64,
                "source_sha256": entry.get("sha256")}

    def read_evidence_bytes(self, evidence_id: str, offset: int = 0,
                            limit: int = MAX_EVIDENCE_READ) -> bytes:
        result = self.read_evidence(evidence_id, offset, limit)
        return base64.b64decode(result["data_b64"]) if result["data"] is None else result["data"].encode("utf-8")


def _resolve_run(run_id: str) -> RunWatchdog:
    run = _RUNS.get(run_id)
    if run is not None:
        return run
    path = Path(run_id)
    if path.is_file():
        for candidate in _RUNS.values():
            if candidate.log_path == path.resolve():
                return candidate
    if path.is_dir() and (path / "state.json").is_file():
        state = json.loads((path / "state.json").read_text(encoding="utf-8"))
        log_name = state.get("log_path")
        if isinstance(log_name, str):
            return RunWatchdog(path.parent / log_name, str(state.get("run_id", run_id)))
    raise EvidenceError("unknown run")


def run_status(run_id: str) -> dict[str, Any]:
    """Read the last published packet without becoming a second recorder."""
    return _resolve_run(run_id).status()


def read_run_evidence(run_id: str, evidence_id: str, offset: int = 0,
                      limit: int = MAX_EVIDENCE_READ) -> dict[str, Any]:
    """Read only an immutable range indexed for ``run_id``."""
    return _resolve_run(run_id).read_evidence(evidence_id, offset, limit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    watch = sub.add_parser("watch", help="poll one run and print status")
    watch.add_argument("--log", required=True, type=Path)
    watch.add_argument("--run-id")
    watch.add_argument("--evidence-dir", type=Path)
    watch.add_argument("--force", action="store_true")
    status = sub.add_parser("status", help="read status for a run directory or registered id")
    status.add_argument("run_id")
    read = sub.add_parser("read", help="read a bounded indexed evidence range")
    read.add_argument("run_id")
    read.add_argument("evidence_id")
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--limit", type=int, default=MAX_EVIDENCE_READ)
    args = parser.parse_args(argv)
    try:
        if args.command == "watch":
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.with_suffix(".supervisor.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise EvidenceError("active supervisor owns recording; use status") from exc
                watchdog = RunWatchdog(args.log, args.run_id, args.evidence_dir)
                result = watchdog.poll(force=args.force)
        elif args.command == "status":
            result = run_status(args.run_id)
        else:
            result = read_run_evidence(args.run_id, args.evidence_id, args.offset, args.limit)
    except (EvidenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
