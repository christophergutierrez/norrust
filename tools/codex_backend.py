#!/usr/bin/env python3
"""Persistent, restricted Codex adapter for the headless client."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__:
    from .request_journal import RequestJournal
else:  # Direct script entry point.
    from request_journal import RequestJournal

def resolved_settings() -> tuple[str, str]:
    model = os.environ.get("NORRUST_CODEX_MODEL", "")
    effort = os.environ.get("NORRUST_CODEX_REASONING_EFFORT", "high")
    if not model:
        raise RuntimeError("NORRUST_CODEX_MODEL is required")
    if not effort:
        raise RuntimeError("NORRUST_CODEX_REASONING_EFFORT must not be empty")
    return model, effort


def session_path() -> Path:
    value = os.environ.get("NORRUST_CODEX_SESSION_FILE", "")
    if not value:
        raise RuntimeError("NORRUST_CODEX_SESSION_FILE is required for persistent Codex play")
    path = Path(value).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def native_instruction(prompt: str) -> str:
    return (
        "You are the continuing model player in a Norrust match. Preserve explicit "
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


def _run_native_once(prompt: str, thread_id: str | None, timeout: float, *,
                     settings: tuple[str, str] | None = None) -> tuple[str, str, list[dict[str, object]]]:
    root = Path(__file__).resolve().parents[1]
    model, effort = settings if settings is not None else resolved_settings()
    if thread_id:
        command = ["codex", "exec", "resume", thread_id, "--json", "--ignore-user-config",
                   "--ignore-rules",
                   "-m", model, "-c", f"model_reasoning_effort={effort}",
                   native_instruction(prompt)]
    else:
        command = ["codex", "exec", "--json", "--ignore-user-config", "--ignore-rules",
                   "--skip-git-repo-check", "--sandbox", "read-only", "--model", model,
                   "--color", "never", "-c", f"model_reasoning_effort={effort}",
                   native_instruction(prompt)]
    process = subprocess.Popen(command, cwd=root, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        group = process.pid
        try:
            os.killpg(group, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=min(5.0, max(0.5, timeout * 0.1)))
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(group, signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=1.0)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = process.communicate()
        raise RuntimeError("native_model_timeout") from exc
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
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


def run_native(prompt: str, thread_id: str | None, timeout: float, *,
               settings: tuple[str, str] | None = None) -> tuple[str, str, list[dict[str, object]]]:
    """Run one native request, retrying transient thread-store writer conflicts.

    A timed-out Codex process can release its thread-store writer slightly after
    the client process has exited. Resuming immediately then produces an
    infrastructure error even though the logical model session is still valid.
    Retry only that explicit transient error; all other failures retain their
    original behavior.
    """
    delays = (2.0, 5.0, 10.0)
    for attempt, delay in enumerate((0.0, *delays)):
        if delay:
            time.sleep(delay)
        try:
            if settings is None:
                return _run_native_once(prompt, thread_id, timeout)
            return _run_native_once(prompt, thread_id, timeout, settings=settings)
        except RuntimeError as exc:
            if "already has an active writer" not in str(exc) or attempt == len(delays):
                raise
    raise AssertionError("unreachable")


def completion_usage(events: list[dict[str, object]]) -> dict[str, int] | None:
    """Return the provider usage attached to the completed native turn."""
    for event in reversed(events):
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if isinstance(usage, dict):
            return {key: value for key, value in usage.items()
                    if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)}
    return None


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


def write_artifact(path: Path, kind: str, turn: int, value: str | dict[str, object]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    suffix = "txt" if isinstance(value, str) else "json"
    target = path / (f"{turn:05d}-{kind}.{suffix}")
    if isinstance(value, str):
        target.write_text(value)
    else:
        target.write_text(json.dumps(value, sort_keys=True, indent=2))


def main() -> int:
    settings = resolved_settings()
    model, effort = settings
    path = session_path()
    prompt = sys.stdin.read()
    state: dict[str, object] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("invalid Codex session sidecar") from exc
    thread_id = state.get("thread_id") if isinstance(state.get("thread_id"), str) else None
    turn = int(state.get("turns", 0)) + 1
    artifact_root = Path(os.environ.get("NORRUST_CODEX_ARTIFACT_DIR", path.parent / "artifacts"))
    session_id = os.environ.get("NORRUST_CODEX_MATCH_ID", str(path))
    timeout = float(os.environ.get("NORRUST_CODEX_TIMEOUT", "840"))
    journal_root = artifact_root / "requests"
    metadata = {"turn": turn, "prompt_sha256": __import__("hashlib").sha256(prompt.encode()).hexdigest(),
                "engine_revision": os.environ.get("NORRUST_ENGINE_REVISION"),
                "deadline_seconds": timeout,
                "requested_model": model, "requested_reasoning_effort": effort}
    with RequestJournal(journal_root, session_id) as journal:
        request = journal.prepare(metadata)
        request.mark_dispatched(native_thread_id=thread_id)
        try:
            write_artifact(artifact_root, "request", turn, prompt)
            new_thread, answer, events = run_native(
                prompt, thread_id, timeout, settings=settings)
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
            identity = {"requested_model": model, "requested_reasoning_effort": effort,
                        "runtime_model": None, "runtime_reasoning_effort": None,
                        "runtime_settings_source": "not_reported"}
            result = {"thread_id": new_thread, "answer": answer, "events": events, **identity,
                      "usage": completion_usage(events)}
            request.complete(result, reply_id=new_thread, native_thread_id=new_thread)
            write_state(path, {"thread_id": new_thread, **identity,
                               "transport": "codex-exec-resume", "turns": turn})
            write_artifact(artifact_root, "result", turn, result)
            sys.stdout.write(json.dumps({"text": answer, "usage": completion_usage(events), "cache": {
                "native_session_id": new_thread, "transport": "codex-exec-resume",
                **identity,
                "tool_restriction": "read-only game prompt; unrelated tools rejected",
                "request_id": request.request_id,
            }}, separators=(",", ":")))
        except RuntimeError as exc:
            if request.state == "dispatched":
                if str(exc) == "native_model_timeout":
                    request.interrupt(error=str(exc), cleanup_verified=True)
                else:
                    request.mark_unknown(error=str(exc))
            raise
    return 0


def cli() -> int:
    argparse.ArgumentParser(description=(
        "Persistent Codex model backend. Configure NORRUST_CODEX_MODEL, "
        "NORRUST_CODEX_REASONING_EFFORT, and "
        "NORRUST_CODEX_SESSION_FILE; reads the canonical prompt from stdin."
    )).parse_args()
    try:
        return main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
