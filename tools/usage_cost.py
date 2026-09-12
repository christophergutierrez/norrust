"""Dated, per-model cost accounting for normalized model calls.

Rates are explicit evidence supplied by a JSON file.  A mixed player/observer
run is evaluated per physical call so a single model price is never applied to
both roles accidentally.  Missing rates or token fields produce unknown cost,
never a zero.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model_usage import ModelCall, TOKEN_FIELDS, normalize_int


class RateFileError(ValueError):
    pass


def load_rates(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = value.get("rates") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not rows:
        raise RateFileError("rate file must contain a non-empty rates array")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("model"), str) or not row["model"]:
            raise RateFileError("each rate requires a model")
        try:
            effective = _datetime.date.fromisoformat(row["effective_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RateFileError("each rate requires ISO effective_date") from exc
        for key in ("input_per_million", "cached_input_per_million", "output_per_million"):
            if type(row.get(key)) not in (int, float) or row[key] < 0:
                raise RateFileError(f"invalid rate: {key}")
        if type(row.get("reasoning_included_in_output")) is not bool:
            raise RateFileError("reasoning_included_in_output must be boolean")
        if not row["reasoning_included_in_output"]:
            if type(row.get("reasoning_per_million")) not in (int, float) or row["reasoning_per_million"] < 0:
                raise RateFileError("reasoning_per_million required when reasoning is separately priced")
        result.append(dict(row, _effective=effective))
    return result


def _call_date(call: ModelCall) -> _datetime.date | None:
    for value in (call.ended_at, call.started_at):
        if isinstance(value, str):
            try:
                return _datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                try:
                    # Existing adapters historically serialized Unix seconds
                    # as strings; preserve their date when it is explicit.
                    instant = _datetime.datetime.fromtimestamp(float(value), tz=_datetime.timezone.utc)
                    return instant.date()
                except (ValueError, OverflowError, OSError):
                    continue
    return None


def _rate_for(call: ModelCall, rates: list[dict[str, Any]]) -> dict[str, Any] | None:
    model = call.reported_model or call.requested_model
    if not isinstance(model, str) or not model:
        return None
    date = _call_date(call)
    if date is None:
        return None
    candidates = [rate for rate in rates if rate["model"] == model and rate["_effective"] <= date]
    return max(candidates, key=lambda rate: rate["_effective"]) if candidates else None


def cost_for_call(call: ModelCall, rates: list[dict[str, Any]]) -> float | None:
    rate = _rate_for(call, rates)
    if rate is None or call.input_tokens is None or call.output_tokens is None:
        return None
    inp, inp_gap = normalize_int(call.input_tokens)
    out, out_gap = normalize_int(call.output_tokens)
    cached, cached_gap = normalize_int(call.cached_input_tokens)
    if inp is None or out is None or inp_gap or out_gap:
        return None
    if cached is None:
        if rate["input_per_million"] != rate["cached_input_per_million"]:
            return None
        cached = 0
    if cached_gap or cached > inp:
        return None
    cost = ((inp - cached) * rate["input_per_million"] +
            cached * rate["cached_input_per_million"] + out * rate["output_per_million"])
    if not rate["reasoning_included_in_output"]:
        reasoning, gap = normalize_int(call.reasoning_tokens)
        if reasoning is None or gap:
            return None
        cost += reasoning * rate["reasoning_per_million"]
    return cost / 1_000_000


def role_cost_report(calls: Iterable[ModelCall], rate_file: str | Path) -> dict[str, Any]:
    rates = load_rates(rate_file)
    members = list(calls)
    buckets = {
        "player": [call for call in members if call.call_role == "player"],
        "observer": [call for call in members if call.call_role == "observer"],
        "unknown": [call for call in members if call.call_role is None],
        "combined": members,
    }
    result: dict[str, Any] = {}
    rates_used = sorted({
        (rate["model"], rate["effective_date"])
        for call in members
        for rate in [_rate_for(call, rates)]
        if rate is not None
    })
    for role, group in buckets.items():
        values = [cost_for_call(call, rates) for call in group]
        known = [value for value in values if value is not None]
        result[role] = {
            "cost_usd": round(sum(known), 9) if known else None,
            "known_calls": len(known), "unknown_calls": len(values) - len(known),
            "call_count": len(values),
            "coverage": ("empty" if not values else
                          "complete" if len(known) == len(values) else
                          "partial" if known else "unknown"),
        }
    result["rate_file"] = str(Path(rate_file).resolve())
    result["rate_source"] = "dated_effective_rate_per_call"
    try:
        result["rate_sha256"] = hashlib.sha256(Path(rate_file).read_bytes()).hexdigest()
    except OSError:
        result["rate_sha256"] = None
    result["rates_used"] = [{"model": model, "effective_date": effective}
                             for model, effective in rates_used]
    return result
