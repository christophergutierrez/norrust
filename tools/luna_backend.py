#!/usr/bin/env python3
"""Persistent, restricted Luna adapter for the headless client."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .luna_request_journal import RequestJournal
except ImportError:  # pragma: no cover - direct script compatibility
    from luna_request_journal import RequestJournal

MODEL = "gpt-5.6-luna"
EFFORT = "high"


def session_path() -> Path:
    value = os.environ.get("NORRUST_LUNA_SESSION_FILE")
    if not value:
        raise RuntimeError("NORRUST_LUNA_SESSION_FILE is required for persistent Luna play")
    path = Path(value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def native_instruction(prompt: str) -> str:
    return (
        "You are the continuing Luna player in a Norrust match. Preserve explicit "
        "objectives across turns, but treat the latest authoritative board and accepted "
        "engine results as current. Return JSON only: a legal action array, an actions "
        "envelope with optional intent and agenda, or one read-only game inspection "
        "request allowed by the current prompt. Use only the game tools described by the "
        "prompt. Do not use shell, web, files, skills, connectors, or unrelated tools.\n\n"
        + prompt
    )


def extract(events: list[dict[str, object]]) -> tuple[str, str]:
    thread_id = ""
    answer = ""
    for event in events:
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                answer = item["text"].strip()
        if event.get("type") == "error":
            raise RuntimeError(str(event))
    if not answer:
        raise RuntimeError("native Codex response did not contain an agent message")
    return thread_id, answer


def run_native(prompt: str, thread_id: str | None, timeout: float) -> tuple[str, str, list[dict[str, object]]]:
    root = Path(__file__).resolve().parents[1]
    if thread_id:
        command = ["codex", "exec", "resume", thread_id, "--json", "--ignore-user-config",
                   "--ignore-rules", "-m", MODEL, "-c", f"model_reasoning_effort={EFFORT}", prompt]
    else:
        command = ["codex", "exec", "--json", "--ignore-user-config", "--ignore-rules",
                   "--skip-git-repo-check", "--sandbox", "read-only", "--model", MODEL,
                   "--color", "never", "-c", f"model_reasoning_effort={EFFORT}",
                   native_instruction(prompt)]
    try:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("native_model_timeout") from exc
    if result.returncode:
        raise RuntimeError("native Codex failed: " + result.stderr[-2000:])
    events: list[dict[str, object]] = []
    for raw in result.stdout.splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    new_thread, answer = extract(events)
    return new_thread or thread_id or "", answer, events


def write_state(path: Path, state: dict[str, object]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_artifact(kind: str, turn: int, value: str | dict[str, object]) -> None:
    directory = os.environ.get("NORRUST_LUNA_ARTIFACT_DIR")
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    suffix = "txt" if isinstance(value, str) else "json"
    target = path / (f"{turn:05d}-{kind}.{suffix}")
    if isinstance(value, str):
        target.write_text(value)
    else:
        target.write_text(json.dumps(value, sort_keys=True, indent=2))


def main() -> int:
    prompt = sys.stdin.read()
    path = session_path()
    state: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("invalid Luna session sidecar") from exc
    thread_id = state.get("thread_id") if isinstance(state.get("thread_id"), str) else None
    turn = int(state.get("turns", 0)) + 1
    artifact_root = Path(os.environ.get("NORRUST_LUNA_ARTIFACT_DIR", path.parent / "artifacts"))
    session_id = os.environ.get("NORRUST_LUNA_MATCH_ID", str(path))
    journal_root = artifact_root / "requests"
    metadata = {"turn": turn, "prompt_sha256": __import__("hashlib").sha256(prompt.encode()).hexdigest(),
                "engine_revision": os.environ.get("NORRUST_ENGINE_REVISION"),
                "deadline_seconds": os.environ.get("NORRUST_LUNA_TIMEOUT", "840")}
    with RequestJournal(journal_root, session_id) as journal:
        request = journal.prepare(metadata)
        request.mark_dispatched(native_thread_id=thread_id)
        try:
            write_artifact("request", turn, prompt)
            new_thread, answer, events = run_native(
                prompt, thread_id, float(os.environ.get("NORRUST_LUNA_TIMEOUT", "840")))
            for event in events:
                request.append_event(event)
            if not new_thread:
                raise RuntimeError("native Codex did not report a thread id")
            if not any(event.get("type") == "turn.completed" for event in events):
                request.mark_unknown(reason="native response lacked turn.completed")
                raise RuntimeError("native Codex response lacked a completed turn")
            forbidden = {"command_execution", "web_search", "skill", "connector"}
            observed = [event.get("item", {}).get("type") for event in events
                        if isinstance(event.get("item"), dict)]
            if any(item in forbidden for item in observed):
                request.fail(reason="native tool restriction violated")
                raise RuntimeError("native tool restriction violated")
            result = {"thread_id": new_thread, "answer": answer, "events": events,
                      "model": MODEL, "reasoning_effort": EFFORT}
            request.complete(result, reply_id=new_thread, native_thread_id=new_thread)
            write_state(path, {"thread_id": new_thread, "model": MODEL, "reasoning_effort": EFFORT,
                               "transport": "codex-exec-resume", "turns": turn})
            write_artifact("result", turn, result)
            sys.stdout.write(json.dumps({"text": answer, "cache": {
                "native_session_id": new_thread, "transport": "codex-exec-resume",
                "runtime_model": MODEL, "runtime_reasoning_effort": EFFORT,
                "tool_restriction": "read-only game prompt; unrelated tools rejected",
                "request_id": request.request_id,
            }}, separators=(",", ":")))
        except RuntimeError as exc:
            if request.state == "dispatched":
                request.mark_unknown(error=str(exc))
            raise
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
