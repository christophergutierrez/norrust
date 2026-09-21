"""Portable decision capsules: a relocatable snapshot of one model-boundary
decision, restorable and offline-queryable without its original absolute
paths or archive layout.

This generalizes the relocatable-checkpoint convention already proven by
`tools/fixtures/decision_positions/` (board path replaced with the literal
`__SCENARIO_BOARD__`, resolved against the checked-out repo, digest-verified
before use) and the restoration machinery in `tools/tactical_comparison.py`
(materialize -> spawn driver -> query -> collect). A capsule bundles that
checkpoint together with the companion client state (`policy`, `progress`,
request context) a live client would have carried at the same boundary, so a
capsule built from richer evidence can support a full offline client replay
while a capsule built from checkpoint alone still supports board-only
analysis -- honestly, never by assuming a default for what is missing.

Hard rules (from `tmp/analysis-exec/CAPSULE-CONTRACT.md`), enforced here:

1. Never advance a board to make a capsule convenient. A boundary that is
   not an exact `model` boundary with `pending_opponent_turn is False` is
   `capability: "unsupported_boundary"`, and this module refuses to launch
   the driver against it.
2. Private replay state (engine RNG, future state) never gets mixed into a
   model-visible observation. `CapsuleHandle` keeps them in separate fields.
3. A deterministic replay mismatch is reported as an integrity defect, with
   both sides shown -- never interpreted as evidence of bad strategy.
4. `capability` is computed here and written into `capsule.json`. Readers
   must trust that field, not re-derive it from which files happen to exist.
5. Original archives are never modified; every build asserts the source
   checkpoint bytes are unchanged afterward.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import tactical_comparison as _tc

ROOT = Path(__file__).resolve().parents[1]

CAPSULE_SCHEMA_VERSION = 1

CAPSULE_MANIFEST_NAME = "capsule.json"
CAPSULE_CHECKPOINT_NAME = "checkpoint.json"
CAPSULE_POLICY_NAME = "policy.json"
CAPSULE_PROGRESS_NAME = "progress.json"
CAPSULE_REQUEST_CONTEXT_NAME = "request_context.json"

# The prior-art placeholder from tools/fixtures/decision_positions/README.md.
BOARD_PLACEHOLDER = "__SCENARIO_BOARD__"

CAPABILITY_FULL_CLIENT_REPLAY = "full_client_replay"
CAPABILITY_BOARD_ONLY = "board_only"
CAPABILITY_UNSUPPORTED_BOUNDARY = "unsupported_boundary"
CAPABILITIES = frozenset({
  CAPABILITY_FULL_CLIENT_REPLAY, CAPABILITY_BOARD_ONLY, CAPABILITY_UNSUPPORTED_BOUNDARY,
})

# Required top-level checkpoint fields, per the measured facts in the
# contract. Missing any of these means the checkpoint cannot be trusted to
# relaunch the driver, so building from it is a hard error.
_REQUIRED_CHECKPOINT_FIELDS = (
  "version", "save_state", "side_turns", "next_id", "boundary",
  "pending_opponent_turn", "scenario", "faction0", "faction1", "llm_side",
  "starting_gold", "seed", "max_turns", "incremental_turns", "board_path",
  "board_sha256",
)


class CapsuleError(Exception):
  """Base class for decision-capsule failures."""


class CapsuleUnsupportedBoundaryError(CapsuleError):
  """Raised when restoration is attempted against a capability that cannot
  be restored exactly. Never silently advance the board instead."""


class CapsuleIntegrityError(CapsuleError):
  """Raised when a capsule fails validation and the caller asked to treat
  that as fatal (restore_capsule always does; validate_capsule never
  raises -- it reports)."""


def _dump(data: Any) -> bytes:
  return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
  return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
  return _sha256_bytes(path.read_bytes())


def _read_json(path: Path) -> Any:
  return json.loads(path.read_text(encoding="utf-8"))


def _board_file(scenario: str, root: Path) -> Path:
  return root / "scenarios" / scenario / "board.toml"


@dataclass
class CapsuleHandle:
  """A live, restored capsule session.

  `observation` is what a client at this boundary could see: the driver's
  own "state" record. `replay_state` is private replay machinery -- the
  restored checkpoint's `save_state`, including engine RNG -- and must never
  be folded into a prompt or into `observation`. Keeping them as separate
  dataclass fields is deliberate, not incidental.
  """
  process: subprocess.Popen
  capsule_dir: Path
  workspace: Path
  checkpoint_dir: Path
  manifest: dict[str, Any]
  checkpoint: dict[str, Any]        # restored (board-resolved) checkpoint envelope
  observation: dict[str, Any]       # the driver's initial "state" record (model-visible)
  replay_state: dict[str, Any]      # private: save_state incl. rng_state, engine internals
  policy: dict[str, Any] | None = None
  progress: dict[str, Any] | None = None
  request_context: dict[str, Any] | None = None
  records: list[dict[str, Any]] = field(default_factory=list)


def build_capsule(
  checkpoint_path: Path,
  capsule_dir: Path,
  *,
  source: dict[str, Any],
  decision: dict[str, Any] | None = None,
  policy: dict[str, Any] | None = None,
  progress: dict[str, Any] | None = None,
  request_context: dict[str, Any] | None = None,
  driver_path: Path | None = None,
  root: Path = ROOT,
) -> dict[str, Any]:
  """Build a portable capsule from one driver checkpoint.

  `source` carries provenance identity: `{archive, game_id, source_commit,
  dirty_patch_hash}`. `decision` optionally carries identities from the
  evidence contract (`decision_id`, `side_turn_id`, `request_id`) --
  `state_revision` is always read from the checkpoint itself, never taken on
  faith from the caller, so it cannot drift from what was actually restored.

  Raises `CapsuleError` (or a `ValueError`/`RuntimeError` subclass of it) on
  malformed input. This function does not swallow bad input -- an invalid
  checkpoint or a board digest mismatch is a hard stop, not a degraded
  capability. Missing companion state (`policy`/`progress`/
  `request_context`), by contrast, is not an error: it lowers `capability`.
  """
  checkpoint_bytes = checkpoint_path.read_bytes()
  data = json.loads(checkpoint_bytes)

  missing = [f for f in _REQUIRED_CHECKPOINT_FIELDS if f not in data]
  if missing:
    raise CapsuleError(f"checkpoint is missing required fields: {missing}")
  save_state = data["save_state"]
  if not isinstance(save_state, dict) or "board_path" not in save_state:
    raise CapsuleError("checkpoint save_state is missing board_path")
  side_turns = data["side_turns"]
  revision = save_state.get("state_revision")
  if not isinstance(side_turns, int) or isinstance(side_turns, bool):
    raise CapsuleError("checkpoint side_turns is not a valid integer")
  if not isinstance(revision, int) or isinstance(revision, bool):
    raise CapsuleError("checkpoint save_state.state_revision is not a valid integer")

  scenario = data["scenario"]
  board_file = _board_file(scenario, root)
  if not board_file.is_file():
    raise CapsuleError(f"maintained board for scenario {scenario!r} is missing")
  board_bytes = board_file.read_bytes()
  board_hash = _sha256_bytes(board_bytes)
  if data["board_sha256"] != board_hash:
    # Hard rule 1: never advance/repair a board to make a capsule
    # convenient. A digest mismatch means the maintained board has drifted
    # from what this checkpoint was recorded against -- that is an
    # integrity problem to surface, not something to paper over here.
    raise CapsuleError(
      "checkpoint board_sha256 does not match the maintained scenario board; "
      "refusing to build a capsule against a drifted board")

  boundary_kind = data["boundary"]
  pending_opponent_turn = data["pending_opponent_turn"]
  boundary_restorable = boundary_kind == "model" and pending_opponent_turn is False

  placeheld = copy.deepcopy(data)
  placeheld["board_path"] = BOARD_PLACEHOLDER
  placeheld["save_state"]["board_path"] = BOARD_PLACEHOLDER
  checkpoint_encoded = _dump(placeheld)
  checkpoint_body_hash = _sha256_bytes(checkpoint_encoded)

  capsule_dir.mkdir(parents=True, exist_ok=True)
  (capsule_dir / CAPSULE_CHECKPOINT_NAME).write_bytes(checkpoint_encoded)

  policy_hash = None
  if policy is not None:
    encoded = _dump(policy)
    (capsule_dir / CAPSULE_POLICY_NAME).write_bytes(encoded)
    policy_hash = _sha256_bytes(encoded)

  progress_hash = None
  if progress is not None:
    encoded = _dump(progress)
    (capsule_dir / CAPSULE_PROGRESS_NAME).write_bytes(encoded)
    progress_hash = _sha256_bytes(encoded)

  if request_context is not None:
    (capsule_dir / CAPSULE_REQUEST_CONTEXT_NAME).write_bytes(_dump(request_context))

  driver_hash = None
  provenance_gaps: dict[str, str] = {}
  if driver_path is not None and driver_path.is_file():
    driver_hash = _sha256_file(driver_path)
  elif driver_path is not None:
    provenance_gaps["driver"] = "driver binary path given but not present at build time"

  if not boundary_restorable:
    capability = CAPABILITY_UNSUPPORTED_BOUNDARY
    provenance_gaps["boundary"] = (
      f"boundary={boundary_kind!r} pending_opponent_turn={pending_opponent_turn!r} "
      "cannot be restored exactly")
  elif policy is not None and progress is not None and request_context is not None:
    capability = CAPABILITY_FULL_CLIENT_REPLAY
  else:
    capability = CAPABILITY_BOARD_ONLY
    if policy is None:
      provenance_gaps["policy"] = "companion policy state not available"
    if progress is None:
      provenance_gaps["progress"] = "companion progress state not available"
    if request_context is None:
      provenance_gaps["request_context"] = "request context not captured"

  decision = dict(decision) if decision else {}
  # The checkpoint is ground truth for the revision, so its value always wins.
  # But a caller that supplied a DIFFERENT revision has a bug, and silently
  # correcting it would hide that bug -- exactly what the frozen contract
  # forbids: "a reference conflict is a conflict, not permission to select the
  # most convenient artifact". Keep the checkpoint's value and record the
  # contradiction so the mistake is visible to whoever made it.
  supplied_revision = decision.get("state_revision")
  if supplied_revision is not None and supplied_revision != revision:
    decision["state_revision_conflict"] = {
      "supplied": supplied_revision,
      "checkpoint": revision,
      "resolution": "checkpoint value used; the supplied revision is wrong",
    }
  decision["state_revision"] = revision
  decision.setdefault("decision_id", None)
  decision.setdefault("side_turn_id", None)
  decision.setdefault("request_id", None)

  manifest = {
    "capsule_schema_version": CAPSULE_SCHEMA_VERSION,
    "source": dict(source),
    "decision": decision,
    "boundary": {
      "kind": boundary_kind,
      "pending_opponent_turn": pending_opponent_turn,
      "side_turns": side_turns,
    },
    "launch": {
      "scenario": scenario,
      "faction0": data["faction0"],
      "faction1": data["faction1"],
      "gold": data["starting_gold"],
      "seed": data["seed"],
      "llm_side": data["llm_side"],
      "max_turns": data["max_turns"],
      "incremental_turns": data["incremental_turns"],
    },
    "hashes": {
      "checkpoint_body": checkpoint_body_hash,
      "board": board_hash,
      "driver": driver_hash,
      "policy": policy_hash,
      "progress": progress_hash,
    },
    "capability": capability,
    "provenance_gaps": provenance_gaps,
  }
  (capsule_dir / CAPSULE_MANIFEST_NAME).write_bytes(_dump(manifest))

  # Hard rule 5: the source archive is never modified. This is a real
  # assertion, not documentation -- if capsule_dir aliased the source
  # directory (a caller error), catch it here rather than shipping a
  # capsule that silently corrupted the archive it was built from.
  if checkpoint_path.read_bytes() != checkpoint_bytes:
    raise CapsuleError("source checkpoint was modified while building the capsule")

  return manifest


def validate_capsule(capsule_dir: Path, *, root: Path = ROOT) -> dict[str, Any]:
  """Validate a capsule directory. Never raises -- a bad capsule is reported
  as structured problems, not an exception, since this is the function a
  caller uses specifically to find out whether a capsule (possibly copied
  from elsewhere, possibly corrupted) is trustworthy.

  Returns `{"ok": bool, "capability": str | None, "problems": list[str]}`.
  """
  problems: list[str] = []
  manifest_path = capsule_dir / CAPSULE_MANIFEST_NAME
  if not manifest_path.is_file():
    return {"ok": False, "capability": None, "problems": ["capsule.json is missing"]}
  try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  except (OSError, ValueError) as error:
    return {"ok": False, "capability": None, "problems": [f"capsule.json is not valid JSON: {error}"]}
  if not isinstance(manifest, dict):
    return {"ok": False, "capability": None, "problems": ["capsule.json does not contain an object"]}

  if manifest.get("capsule_schema_version") != CAPSULE_SCHEMA_VERSION:
    problems.append(
      f"capsule_schema_version {manifest.get('capsule_schema_version')!r} "
      f"!= supported {CAPSULE_SCHEMA_VERSION}")

  hashes = manifest.get("hashes") if isinstance(manifest.get("hashes"), dict) else {}
  launch = manifest.get("launch") if isinstance(manifest.get("launch"), dict) else {}
  decision = manifest.get("decision") if isinstance(manifest.get("decision"), dict) else {}
  boundary = manifest.get("boundary") if isinstance(manifest.get("boundary"), dict) else {}

  checkpoint_path = capsule_dir / CAPSULE_CHECKPOINT_NAME
  checkpoint_data: dict[str, Any] | None = None
  if not checkpoint_path.is_file():
    problems.append("checkpoint.json is missing")
  else:
    checkpoint_bytes = checkpoint_path.read_bytes()
    actual_hash = _sha256_bytes(checkpoint_bytes)
    expected_hash = hashes.get("checkpoint_body")
    if actual_hash != expected_hash:
      problems.append(
        "checkpoint body hash mismatch: capsule.json says "
        f"{expected_hash!r}, checkpoint.json is {actual_hash!r}")
    try:
      checkpoint_data = json.loads(checkpoint_bytes)
    except ValueError as error:
      problems.append(f"checkpoint.json is not valid JSON: {error}")
      checkpoint_data = None

  if checkpoint_data is not None:
    save_state = checkpoint_data.get("save_state")
    if (checkpoint_data.get("board_path") != BOARD_PLACEHOLDER
        or not isinstance(save_state, dict)
        or save_state.get("board_path") != BOARD_PLACEHOLDER):
      problems.append("checkpoint.json does not carry the __SCENARIO_BOARD__ placeholder; not relocatable")

    revision = save_state.get("state_revision") if isinstance(save_state, dict) else None
    if decision.get("state_revision") != revision:
      problems.append(
        f"decision.state_revision {decision.get('state_revision')!r} "
        f"!= checkpoint save_state.state_revision {revision!r}")

    scenario = launch.get("scenario") or checkpoint_data.get("scenario")
    if isinstance(scenario, str):
      board_file = _board_file(scenario, root)
      if not board_file.is_file():
        problems.append(f"maintained board for scenario {scenario!r} is missing")
      else:
        actual_board_hash = _sha256_file(board_file)
        expected_board_hash = hashes.get("board")
        if actual_board_hash != expected_board_hash:
          problems.append(
            "board hash mismatch: capsule.json says "
            f"{expected_board_hash!r}, maintained board is {actual_board_hash!r}")
        if checkpoint_data.get("board_sha256") not in (None, actual_board_hash):
          problems.append(
            "checkpoint board_sha256 does not match the maintained scenario board")
    else:
      problems.append("launch.scenario is missing; cannot resolve the board placeholder")

  for name, hash_key in ((CAPSULE_POLICY_NAME, "policy"), (CAPSULE_PROGRESS_NAME, "progress")):
    path = capsule_dir / name
    if path.is_file():
      actual = _sha256_file(path)
      expected = hashes.get(hash_key)
      if actual != expected:
        problems.append(f"{name} hash mismatch: capsule.json says {expected!r}, file is {actual!r}")

  capability = manifest.get("capability")
  if capability not in CAPABILITIES:
    problems.append(f"capability {capability!r} is not one of {sorted(CAPABILITIES)}")
  elif capability == CAPABILITY_FULL_CLIENT_REPLAY:
    for name in (CAPSULE_POLICY_NAME, CAPSULE_PROGRESS_NAME, CAPSULE_REQUEST_CONTEXT_NAME):
      if not (capsule_dir / name).is_file():
        problems.append(f"capability={CAPABILITY_FULL_CLIENT_REPLAY!r} but {name} is missing")
  elif capability == CAPABILITY_BOARD_ONLY:
    companion_present = all((capsule_dir / name).is_file() for name in (
      CAPSULE_POLICY_NAME, CAPSULE_PROGRESS_NAME, CAPSULE_REQUEST_CONTEXT_NAME))
    if companion_present:
      problems.append(
        f"capability={CAPABILITY_BOARD_ONLY!r} but full companion state is present; "
        f"should be {CAPABILITY_FULL_CLIENT_REPLAY!r}")
  elif capability == CAPABILITY_UNSUPPORTED_BOUNDARY:
    if boundary.get("kind") == "model" and boundary.get("pending_opponent_turn") is False:
      problems.append(
        f"capability={CAPABILITY_UNSUPPORTED_BOUNDARY!r} but boundary is an exact "
        "restorable model boundary")

  return {"ok": not problems, "capability": capability, "problems": problems}


def restore_capsule(
  capsule_dir: Path,
  driver_path: Path,
  workspace: Path,
  *,
  root: Path = ROOT,
) -> CapsuleHandle:
  """Restore a capsule into an isolated workspace and launch the driver
  against it, using the capsule's OWN recorded launch parameters -- never
  hardcoded ones. Returns a live `CapsuleHandle` for offline queries.

  Refuses (`CapsuleUnsupportedBoundaryError`) when `capability` is
  `unsupported_boundary`: the whole point of that capability value is that
  restoring this capsule exactly is not possible, and launching the driver
  against a best-effort substitute would be exactly the falsified-evidence
  failure mode the contract forbids.
  """
  report = validate_capsule(capsule_dir, root=root)
  if not report["ok"]:
    raise CapsuleIntegrityError(
      "capsule failed validation, refusing to restore: " + "; ".join(report["problems"]))
  if report["capability"] == CAPABILITY_UNSUPPORTED_BOUNDARY:
    raise CapsuleUnsupportedBoundaryError(
      "capsule boundary cannot be restored exactly (capability=unsupported_boundary); "
      "never advance the board to make this convenient")

  manifest = json.loads((capsule_dir / CAPSULE_MANIFEST_NAME).read_text(encoding="utf-8"))
  data = json.loads((capsule_dir / CAPSULE_CHECKPOINT_NAME).read_bytes())
  launch = manifest["launch"]
  scenario = launch["scenario"]
  board_file = _board_file(scenario, root)

  materialized = copy.deepcopy(data)
  materialized["board_path"] = str(board_file)
  materialized["save_state"]["board_path"] = str(board_file)
  encoded = json.dumps(materialized, separators=(",", ":")).encode("utf-8")

  side_turns = data["side_turns"]
  revision = data["save_state"]["state_revision"]
  boundary_kind = data["boundary"]
  digest = _sha256_bytes(encoded)

  workspace.mkdir(parents=True, exist_ok=True)
  checkpoint_dir = workspace / "checkpoints"
  checkpoint_dir.mkdir(exist_ok=True)
  checkpoint_path = workspace / f"{side_turns}-{revision}-{boundary_kind}-{digest}.json"
  checkpoint_path.write_bytes(encoded)

  process = _tc._start(
    checkpoint_path, checkpoint_dir, driver=driver_path, scenario=scenario,
    faction0=launch["faction0"], faction1=launch["faction1"], gold=launch["gold"],
    seed=launch["seed"], llm_side=launch["llm_side"], max_turns=launch["max_turns"],
    incremental_turns=launch["incremental_turns"], repo_root=root,
  )

  records: list[dict[str, Any]] = []
  try:
    initial_records = _tc._read_until(process, "state")
  except Exception:
    _tc._close(process)
    raise
  records.extend(initial_records)
  observation = initial_records[-1]

  policy = None
  if (capsule_dir / CAPSULE_POLICY_NAME).is_file():
    policy = _read_json(capsule_dir / CAPSULE_POLICY_NAME)
  progress = None
  if (capsule_dir / CAPSULE_PROGRESS_NAME).is_file():
    progress = _read_json(capsule_dir / CAPSULE_PROGRESS_NAME)
  request_context = None
  if (capsule_dir / CAPSULE_REQUEST_CONTEXT_NAME).is_file():
    request_context = _read_json(capsule_dir / CAPSULE_REQUEST_CONTEXT_NAME)

  return CapsuleHandle(
    process=process,
    capsule_dir=capsule_dir,
    workspace=workspace,
    checkpoint_dir=checkpoint_dir,
    manifest=manifest,
    checkpoint=materialized,
    observation=observation,
    replay_state={
      "rng_state": data["save_state"].get("rng_state"),
      "save_state": data["save_state"],
    },
    policy=policy,
    progress=progress,
    request_context=request_context,
    records=records,
  )


def capsule_query_fn(handle: CapsuleHandle):
  """Adapt a restored capsule into the narrow QueryFn the evaluator expects.

  `tactical_comparison._query` returns `(final_status, all_records)` because
  its callers need the intermediate driver records. The bounded evaluator only
  needs the final status mapping, so the two shapes are bridged here rather
  than in the evaluator: the evaluator stays a pure function of a callable and
  remains testable without a live driver process.

  An exception is NOT swallowed here. The evaluator censors a failed sample on
  purpose, recording it as visibly incomplete rather than as a zero outcome,
  and it can only do that if the failure actually reaches it.
  """
  def query(payload):
    response, _records = _tc._query(handle.process, dict(payload))
    return response
  return query


def close_capsule_session(handle: CapsuleHandle) -> None:
  _tc._close(handle.process)


def replay_recorded_action(
  capsule_dir: Path,
  driver_path: Path,
  workspace: Path,
  recorded: dict[str, Any],
  *,
  root: Path = ROOT,
) -> dict[str, Any]:
  """Restore the capsule, submit `recorded["actions"]` (a batch, already in
  driver order form) as the chosen action, and compare the outcome against
  what was recorded at capture time.

  `recorded` may carry any of `expected_state_revision`, `expected_events`
  (as returned by the driver's "events" records), `expected_committed`. Only
  the keys present are checked.

  Per contract rule 3: a deterministic mismatch here is an INTEGRITY DEFECT
  -- evidence that replay is not reproducing the recorded run faithfully --
  never a judgment about whether the recorded action was strategically
  good or bad. The return value shows both sides and never editorializes.
  """
  handle = restore_capsule(capsule_dir, driver_path, workspace, root=root)
  try:
    revision = handle.observation["state_revision"]
    actions = list(recorded["actions"])
    validation, validation_records = _tc._query(handle.process, {
      "action": "Query", "what": "validate_batch",
      "state_revision": revision, "orders": actions,
    })
    handle.records.extend(validation_records)
    if validation.get("body", {}).get("valid") is not True:
      return {
        "integrity_defect": True,
        "reason": "recorded action batch failed validation on replay",
        "validation": validation,
      }
    _tc._send(handle.process, actions)
    post_records = _tc._read_until(handle.process, "state", accept_game_end=True)
    handle.records.extend(post_records)
    submit_status = next(
      (r for r in reversed(post_records) if r.get("type") == "status" and "committed" in r), None)
    replayed_state = next((r for r in reversed(post_records) if r.get("type") == "state"), None)
    replayed_events = _tc._events(post_records)

    mismatches: dict[str, Any] = {}
    expected_revision = recorded.get("expected_state_revision")
    if expected_revision is not None:
      actual_revision = replayed_state.get("state_revision") if replayed_state else None
      if actual_revision != expected_revision:
        mismatches["state_revision"] = {"recorded": expected_revision, "replayed": actual_revision}
    expected_events = recorded.get("expected_events")
    if expected_events is not None and replayed_events != expected_events:
      mismatches["events"] = {"recorded": expected_events, "replayed": replayed_events}
    expected_committed = recorded.get("expected_committed")
    if expected_committed is not None:
      actual_committed = submit_status.get("committed") if submit_status else None
      if actual_committed != expected_committed:
        mismatches["committed"] = {"recorded": expected_committed, "replayed": actual_committed}

    return {
      "integrity_defect": bool(mismatches),
      "mismatches": mismatches,
      "replayed_state": replayed_state,
      "replayed_events": replayed_events,
      "submit_status": submit_status,
    }
  finally:
    close_capsule_session(handle)
