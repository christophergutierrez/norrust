"""Shared model response normalization and parsing for actions and tools.

Used by `tools.llm_client`, `tools.publish_reply`, `tools.decision_annotations`,
and `tools.turn_agenda`.
"""
from __future__ import annotations

import json
from typing import Any


# This list intentionally lives beside the parser rather than being inferred
# from arbitrary object keys.  Recovery may identify a pending lookup from a
# malformed response, but it must never turn an arbitrary JSON fragment into a
# request that the driver executes.
RECOGNIZED_BARE_TOOLS = frozenset({
  "preview_batch", "inspect_units", "inspect_target", "inspect_targets", "inspect_hex",
})


class ResponseParseError(ValueError):
  """Raised when a model response cannot be normalized to a single valid JSON payload."""


def recover_bare_tool_prefix(text: str) -> dict[str, Any] | None:
  """Recognize a complete bare-tool object at the start of malformed text.

  This is deliberately a recovery classifier, not an execution parser.  It
  only decodes one JSON value beginning at the first non-whitespace byte and
  returns it when that value is an object naming one of the documented bare
  tools.  Trailing rationale remains untrusted and is never executed; callers
  must obtain a separately parsed, complete corrected response before
  dispatching anything.
  """
  if not isinstance(text, str):
    return None
  start = len(text) - len(text.lstrip())
  if start >= len(text) or text[start] != "{":
    return None
  try:
    value, _end = json.JSONDecoder().raw_decode(text, start)
  except json.JSONDecodeError:
    return None
  name = value.get("tool") if isinstance(value, dict) else None
  if not isinstance(name, str) or name not in RECOGNIZED_BARE_TOOLS:
    return None
  return value


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
