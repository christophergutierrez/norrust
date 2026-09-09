#!/usr/bin/env python3
"""Validate a player's pending reply before publishing it to the file backend.

A file-transport player (`tools/file_backend.py`) writes the complete prompt
to ``prompt_<ID>.txt`` and waits for ``reply_<ID>.txt``. Nothing previously
checked the player's draft reply against the same decision-annotation
validator the client applies after publication, so a mistake such as an
overlong risk string was discovered only after publishing, wasting a full
repair round without the player ever seeing the exact error. This module is
the one local helper: it validates a pending reply against the existing
`tools.decision_annotations` validator, and publishes it exactly once, tied
to the file backend's own request marker.

On failure it never publishes, never overwrites an earlier reply, and never
alters the attempt text; it records the raw attempt bytes/hash next to the
request ID in a small append-only local record (``validation_log.ndjson``,
one JSON object per line) so later tooling can tell a first-attempt success
from a repaired one, and a terminal (never-repaired) failure from an unknown
gap in the evidence. On success it publishes atomically with no overwrite,
using an exclusive filesystem link so concurrent or duplicate publication
attempts can never replace an already-published reply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .decision_annotations import annotation_for_response

VALIDATION_LOG_NAME = "validation_log.ndjson"


class PublishError(ValueError):
    """A pending reply failed local validation or was already published."""


def _find_pending_request(directory: Path, request_id: str | None) -> str:
    if request_id:
        if not (directory / f"prompt_{request_id}.txt").is_file():
            raise PublishError(f"no request found for {request_id}")
        return request_id
    markers = sorted(directory.glob("waiting_*"))
    if not markers:
        raise PublishError(f"no pending request marker found in {directory}")
    if len(markers) > 1:
        names = ", ".join(marker.name for marker in markers)
        raise PublishError(f"multiple pending request markers found ({names}); pass --request-id")
    return markers[0].name.removeprefix("waiting_")


def _record_attempt(directory: Path, request_id: str, raw: bytes, status: str, error: str | None) -> None:
    record = {
        "request_id": request_id,
        "timestamp": time.time(),
        "status": status,
        "error": error,
        "attempt_sha256": hashlib.sha256(raw).hexdigest(),
        "attempt_bytes": len(raw),
    }
    with (directory / VALIDATION_LOG_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def validate_reply_text(text: str) -> dict[str, Any]:
    """Return the existing decision-annotation validator's verdict.

    Tool-only requests (``not_applicable``) and replies with no decisions
    (``missing``, including a bare action array) remain eligible to publish:
    missing annotations can still execute legally. Only ``invalid`` -
    malformed JSON, an unknown rule ID, uncovered actions, empty text, or
    text over the 240 UTF-8 byte cap - blocks publication.
    """
    return annotation_for_response(text)


def publish_reply(pending_path: Path | str, directory: Path | str, request_id: str | None = None) -> str:
    """Validate and publish one pending reply. Returns the resolved request ID.

    Raises ``PublishError`` without publishing, without touching an existing
    reply, and without shortening or otherwise changing the attempt text,
    when validation fails or a reply was already published for this request.
    """
    directory = Path(directory)
    resolved_id = _find_pending_request(directory, request_id)
    reply_path = directory / f"reply_{resolved_id}.txt"
    raw = Path(pending_path).read_bytes()
    if reply_path.exists():
        raise PublishError(f"reply already published for {resolved_id}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        _record_attempt(directory, resolved_id, raw, "invalid", f"reply is not valid UTF-8: {exc}")
        raise PublishError(f"reply is not valid UTF-8: {exc}") from None
    annotation = validate_reply_text(text)
    if annotation["status"] == "invalid":
        _record_attempt(directory, resolved_id, raw, "invalid", annotation["error"])
        raise PublishError(annotation["error"])
    # Publish atomically with no overwrite: write the complete, already-
    # validated bytes to a private temp file, then create the destination
    # with an exclusive hard link. os.link fails with FileExistsError if a
    # concurrent or duplicate publish already won, so no separate locking
    # service is needed and readers of reply_path never see a torn write.
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".reply_{resolved_id}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        try:
            os.link(tmp_name, reply_path)
        except FileExistsError:
            raise PublishError(f"reply already published for {resolved_id}") from None
    finally:
        os.unlink(tmp_name)
    _record_attempt(directory, resolved_id, raw, annotation["status"], None)
    return resolved_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path,
                         help="the file backend's request directory")
    parser.add_argument("--pending", required=True, type=Path,
                         help="path to the drafted reply awaiting validation")
    parser.add_argument("--request-id", default=None,
                         help="the request marker's ID; inferred from a single waiting_* marker if omitted")
    args = parser.parse_args(argv)
    try:
        resolved_id = publish_reply(args.pending, args.directory, args.request_id)
    except PublishError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"published {resolved_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
