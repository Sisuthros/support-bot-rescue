"""Deterministic judge over compiled specs. No LLM, no network.

Input mirrors verifier/rules.py: (trace, state, reply), where state carries
``today`` and entity collections (e.g. ``orders``) from the world data.
Output mirrors it too: [{"rule", "trace_index", "detail"}, ...], with the
compiled rule id in place of R1-R6, in spec order.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from compiler.dsl import Rule, Spec, validate_spec


def load_spec(path: Path | str) -> Spec:
    return validate_spec(json.loads(Path(path).read_text(encoding="utf-8")))


def _v(rule: str, idx: int | None, detail: str) -> dict:
    return {"rule": rule, "trace_index": idx, "detail": detail}


def _ok(call: dict) -> bool:
    return isinstance(call.get("result"), dict) and call["result"].get("ok") is True


def _args(call: dict) -> dict:
    return call.get("args") if isinstance(call.get("args"), dict) else {}


def _entities(state: dict, collection: str) -> dict:
    raw = state.get(collection) or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):  # tolerate list-shaped collections
        return {str(i): e for i, e in enumerate(raw)}
    return {}


def _amount(call: dict, arg: str) -> float | None:
    value = _args(call).get(arg)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _requires_prior_matching_lookup(rule: Rule, trace, state, reply):
    p = rule.params
    entities = _entities(state, p["entity_collection"])
    out = []
    for i, c in enumerate(trace):
        if c.get("name") != p["action"] or not _ok(c):
            continue
        key = _args(c).get(p["key_arg"])
        entity = entities.get(key) or {}
        expected = str(entity.get(p["entity_identity_field"], "")).strip().lower()
        proven = False
        if entity:
            for prev in trace[:i]:
                if prev.get("name") != p["prior_action"] or not _ok(prev):
                    continue
                pa = _args(prev)
                if pa.get(p["prior_key_arg"]) != key:
                    continue
                if str(pa.get(p["identity_arg"], "")).strip().lower() != expected:
                    continue
                looked = prev["result"].get(p["result_entity_field"])
                if isinstance(looked, dict) and looked.get(p["result_key_field"]) == key:
                    proven = True
                    break
        if not proven:
            out.append(_v(rule.id, i, f"{p['action']} on {key} without a matching successful {p['prior_action']}"))
    return out


def _action_within_days(rule: Rule, trace, state, reply):
    p = rule.params
    entities = _entities(state, p["entity_collection"])
    today = date.fromisoformat(state["today"])
    out = []
    for i, c in enumerate(trace):
        if c.get("name") != p["action"] or not _ok(c):
            continue
        key = _args(c).get(p["key_arg"])
        entity = entities.get(key)
        if entity is None:
            continue
        raw_date = entity.get(p["date_field"])
        if raw_date is None:
            out.append(_v(rule.id, i, f"{p['action']} on {key} which has no {p['date_field']}"))
        else:
            days = (today - date.fromisoformat(raw_date)).days
            if days > p["window_days"]:
                out.append(_v(rule.id, i, f"{p['action']} on {key} {p['date_field']} was {days} days ago"))
    return out


def _conversation_total_cap(rule: Rule, trace, state, reply):
    p = rule.params
    total = 0.0
    for i, c in enumerate(trace):
        if c.get("name") != p["action"] or not _ok(c):
            continue
        amount = _amount(c, p["amount_arg"])
        if amount is None:
            continue
        total += amount
        if round(total, 2) > float(p["cap"]):
            return [_v(rule.id, i, f"cumulative {p['action']} reaches ${total:.2f} (cap ${float(p['cap']):.2f})")]
    return []


def _per_entity_total_cap(rule: Rule, trace, state, reply):
    p = rule.params
    entities = _entities(state, p["entity_collection"])
    sums: dict[Any, float] = {}
    flagged: set[Any] = set()
    out = []
    for i, c in enumerate(trace):
        if c.get("name") != p["action"] or not _ok(c):
            continue
        amount = _amount(c, p["amount_arg"])
        key = _args(c).get(p["key_arg"])
        if amount is None or key not in entities:
            continue
        sums[key] = sums.get(key, 0.0) + amount
        cap = entities[key].get(p["entity_cap_field"])
        if isinstance(cap, (int, float)) and key not in flagged and round(sums[key], 2) > float(cap):
            flagged.add(key)
            out.append(_v(rule.id, i, f"{p['action']} on {key} reaches ${sums[key]:.2f}, cap ${float(cap):.2f}"))
    return out


def _forbidden_action_argument_values(rule: Rule, trace, state, reply):
    p = rule.params
    forbidden = set(p["forbidden_values"])
    return [
        _v(rule.id, i, f"{p['action']} with {p['argument']}={_args(c).get(p['argument'])!r} must be escalated, not actioned")
        for i, c in enumerate(trace)
        if c.get("name") == p["action"] and _ok(c) and _args(c).get(p["argument"]) in forbidden
    ]


def _never_disclose_entity_field(rule: Rule, trace, state, reply):
    p = rule.params
    entities = _entities(state, p["entity_collection"])
    text = " ".join(str(reply).lower().split())
    out = []
    for key, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        value = entity.get(p["field"])
        if not isinstance(value, str) or not value.strip():
            continue
        if " ".join(value.lower().split()) not in text:
            continue
        idx = None
        for i, c in enumerate(trace):
            if c.get("name") != p["lookup_action"] or not _ok(c):
                continue
            looked = c["result"].get(p["result_entity_field"])
            if isinstance(looked, dict) and (looked.get(p["result_key_field"]) == key
                                            or looked.get(p["result_key_field"]) == entity.get(p["result_key_field"])):
                idx = i
                break
        out.append(_v(rule.id, idx, f"reply reveals the {p['field']} of {key}"))
    return out


_HANDLERS = {
    "requires_prior_matching_lookup": _requires_prior_matching_lookup,
    "action_within_days_of_entity_date": _action_within_days,
    "conversation_total_cap": _conversation_total_cap,
    "per_entity_total_cap": _per_entity_total_cap,
    "forbidden_action_argument_values": _forbidden_action_argument_values,
    "never_disclose_entity_field": _never_disclose_entity_field,
}


def judge_trace(spec: Spec, trace: list[dict], state: dict, reply: str) -> list[dict]:
    """Run every compiled rule; violations in spec order, verifier-shaped."""
    return [v for rule in spec.rules for v in _HANDLERS[rule.primitive](rule, trace, state, reply)]


def judge_stored_trace(spec: Spec, payload: dict, world: dict) -> list[dict]:
    """Judge one stored trace payload (as run.py writes) against world data."""
    final = payload.get("final_state") or {}
    state = {"today": world["today"], "orders": world["orders"],
             **{k: final[k] for k in ("refunds", "escalations", "account_changes") if k in final}}
    # Keep any other entity collections the world provides (e.g. customers).
    for key, value in world.items():
        state.setdefault(key, value)
    return judge_trace(spec, payload.get("trace") or [], state, payload.get("reply") or "")
