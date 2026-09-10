"""Provider model identity classification and validation."""
from __future__ import annotations


def classify_model_identity(
  requested: str | None, reported: str | None
) -> tuple[str, bool]:
  """Classify the relationship between requested model ID and reported model identity.

  Returns (status, is_mismatch) where:
    status is one of:
      - 'verified_match': exact string equality between requested and reported
      - 'unverified_label': reported is a display label (e.g. contains spaces or non-canonical format)
      - 'conflicting_canonical_id': reported is a distinct canonical ID
      - 'unknown': requested or reported is missing
    is_mismatch is True ONLY when reported is an actual conflicting canonical ID.
  """
  if not requested or not reported:
    return "unknown", False

  if requested == reported:
    return "verified_match", False

  # Check if reported is a display label.
  # Display labels typically have spaces (e.g. "Qwen 3.8 Max", "Llama 3.3 70B Instruct").
  # Canonical model IDs do not contain whitespace.
  if " " in reported:
    return "unverified_label", False

  # If reported has no spaces:
  # Check if reported is a leaf slug of requested (e.g. accounts/fireworks/models/qwen3p8-max vs qwen3p8-max)
  if requested.endswith("/" + reported):
    return "unverified_label", False

  # If both are canonical-style identifiers (or start with accounts/ or have / or distinct slugs):
  # They are genuinely different canonical model IDs.
  return "conflicting_canonical_id", True
