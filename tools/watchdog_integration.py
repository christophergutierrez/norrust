"""Integration seam between the recording watchdog and observer controller.

This module has no scheduling side effects beyond loading the current bounded
status packet and proving the catalog identity.  In particular, constructing
the controller never calls the provider; the supervisor can create it before
starting its nonblocking poll loop.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .watchdog_observer import MAX_CALLS, ObserverController


class WatchdogIdentityError(ValueError):
    """No unambiguous catalog conversation identity was proven."""


_IDENTITY_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _candidate(value: Any, source: str, found: list[tuple[str, str]]) -> None:
    if isinstance(value, str) and value and _IDENTITY_RE.fullmatch(value):
        found.append((value, source))


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def prove_catalog_identity(log_path: str | Path, *, run_watchdog: Any | None = None,
                           explicit: str | None = None,
                           request_context_path: str | Path | None = None,
                           metadata_path: str | Path | None = None) -> str:
    """Resolve a catalog game/conversation ID from independent maintained evidence.

    An explicit value is accepted only when it agrees with a packet, context,
    or metadata source.  A supervisor UUID is never treated as a catalog ID by
    itself.
    """
    log = Path(log_path).resolve()
    found: list[tuple[str, str]] = []
    if run_watchdog is not None:
        try:
            packet = run_watchdog.status()
        except Exception as exc:
            raise WatchdogIdentityError(f"watchdog status unavailable: {type(exc).__name__}") from exc
        if isinstance(packet, Mapping):
            _candidate(packet.get("conversation_id"), "status.conversation_id", found)
    context = Path(request_context_path) if request_context_path else log.parent / "request_context.json"
    context_value = _read_json(context)
    if context_value is not None:
        _candidate(context_value.get("conversation_id"), "request_context.json", found)
    metadata = Path(metadata_path) if metadata_path else log.parent / "metadata.json"
    metadata_value = _read_json(metadata)
    if metadata_value is not None:
        _candidate(metadata_value.get("conversation_id"), "metadata.json", found)
    # Match metadata records are small and are maintained by llm_client. Read
    # only a bounded prefix so identity proof cannot consume a growing stream.
    try:
        with log.open("rb") as handle:
            raw = handle.read(256 * 1024)
        for line in raw.splitlines():
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(record, Mapping) and record.get("type") == "metadata":
                _candidate(record.get("conversation_id"), "match.ndjson.metadata", found)
                break
    except OSError:
        pass
    values = {value for value, _source in found}
    if explicit is not None:
        if not isinstance(explicit, str) or not _IDENTITY_RE.fullmatch(explicit):
            raise WatchdogIdentityError("explicit catalog identity is invalid")
        if not values:
            raise WatchdogIdentityError("explicit catalog identity is unproven")
        values.add(explicit)
    if len(values) != 1:
        raise WatchdogIdentityError("catalog identity is missing or conflicting")
    return next(iter(values))


def attach_observer(run_watchdog: Any, log_path: str | Path, *, backend: Any | None = None,
                    mode: str = "off", stop: Any | None = None,
                    state_path: str | Path | None = None,
                    request_context_path: str | Path | None = None,
                    metadata_path: str | Path | None = None,
                    catalog_game_id: str | None = None,
                    usage_sidecar: str | Path | None = None,
                    clock: Any | None = None,
                    max_calls: int = MAX_CALLS) -> ObserverController:
    """Build a controller around an actual ``RunWatchdog`` instance.

    ``run_watchdog.status`` and ``read_evidence`` are adapted to the
    controller callback signatures.  Identity is proven before the controller
    is constructed, so a fresh supervisor run UUID cannot create foreign
    ``model_calls`` rows.
    """
    log = Path(log_path).resolve()
    identity = prove_catalog_identity(
        log, run_watchdog=run_watchdog, explicit=catalog_game_id,
        request_context_path=request_context_path, metadata_path=metadata_path)
    run_id = str(getattr(run_watchdog, "run_id", ""))
    if not run_id:
        raise WatchdogIdentityError("RunWatchdog has no run_id")
    root = Path(getattr(run_watchdog, "watchdog_dir", log.parent / f"{log.stem}.watchdog"))
    observer_state = Path(state_path) if state_path else root / "observer-state.json"
    sidecar = Path(usage_sidecar) if usage_sidecar else log.parent / "usage.ndjson"
    if backend is None:
        from .watchdog_observer import FireworksObserverBackend
        backend = FireworksObserverBackend()
    read = getattr(run_watchdog, "read_evidence")
    kwargs = {
        "catalog_game_id": identity,
        "backend": backend,
        "mode": mode,
        "progress": lambda _run_id: run_watchdog.status(),
        "evidence_reader": lambda _run_id, evidence_id, offset, limit: read(evidence_id, offset, limit),
        "stop": stop,
        "usage_sidecar": sidecar,
        "max_calls": max_calls,
    }
    if clock is not None:
        kwargs["clock"] = clock
    return ObserverController(run_id, observer_state, **kwargs)
