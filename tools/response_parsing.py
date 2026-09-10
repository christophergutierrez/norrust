"""Shared model response normalization and parsing for actions and tools.

Used by `tools.llm_client`, `tools.publish_reply`, `tools.decision_annotations`,
and `tools.turn_agenda`.
"""
from __future__ import annotations

import json
from typing import Any


class ResponseParseError(ValueError):
  """Raised when a model response cannot be normalized to a single valid JSON payload."""


def parse_action_response(text: str) -> Any:
  """Normalize a complete action or tool reply.

  Accepts:
    - Raw JSON (dict or list)
    - Exactly one complete fenced JSON payload surrounded by prose/explanation

  Rejects:
    - Empty text or non-string
    - Multiple candidate code blocks / payloads
    - Truncated fences (unclosed code fence)
    - Invalid JSON inside or outside fences
    - Unsupported JSON root types (numbers, booleans, strings, null)
    - Arbitrary un-fenced prose (no greedy brace extraction)
  """
  if not isinstance(text, str):
    raise ResponseParseError("response must be a string")
  stripped = text.strip()
  if not stripped:
    raise ResponseParseError("empty response")

  direct_error_msg = ""
  try:
    decoded = json.loads(stripped)
    if not isinstance(decoded, (dict, list)):
      raise ResponseParseError(
        f"unsupported response shape: {type(decoded).__name__}; expected object or array"
      )
    return decoded
  except json.JSONDecodeError as direct_exc:
    # Raw JSON failed; check if it contains markdown code fences.
    direct_error_msg = direct_exc.msg

  # 2. Look for code fences (lines with ```).
  lines = text.splitlines(keepends=True)
  fence_indices: list[int] = []
  for i, line in enumerate(lines):
    stripped_line = line.strip()
    if stripped_line.startswith("```"):
      fence_indices.append(i)

  if not fence_indices:
    # No fences and raw JSON failed: reject. Do not use greedy brace extraction.
    detail = f": {direct_error_msg}" if direct_error_msg else ""
    raise ResponseParseError(f"response is not valid JSON{detail}")

  if len(fence_indices) % 2 != 0 or len(fence_indices) < 2:
    raise ResponseParseError(
      "truncated code fence: opening fence without matching closing fence"
    )

  if len(fence_indices) > 2:
    raise ResponseParseError(
      "multiple candidate payloads: response contains multiple code blocks"
    )

  start_idx, end_idx = fence_indices[0], fence_indices[1]
  fenced_content = "".join(lines[start_idx + 1:end_idx]).strip()
  if not fenced_content:
    raise ResponseParseError("empty code fence content")

  try:
    decoded = json.loads(fenced_content)
  except json.JSONDecodeError as exc:
    raise ResponseParseError(f"invalid JSON in code fence: {exc.msg}") from exc

  if not isinstance(decoded, (dict, list)):
    raise ResponseParseError(
      f"unsupported response shape: {type(decoded).__name__}; expected object or array"
    )

  return decoded
