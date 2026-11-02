"""Closed, typed rule vocabulary for compiled support policies.

The LLM may only emit rules using the primitives below. Plain code
(:mod:`compiler.spec_judge`) interprets them; anything outside this
vocabulary is rejected here, before any judging happens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SPEC_VERSION = "1.0"

class SpecError(ValueError):
    """A candidate spec is outside the closed DSL."""

# primitive -> {param name: type tag}. Type tags: string, positive_int,
# positive_number, string_list. Every listed param is required; no others pass.
PRIMITIVES: dict[str, dict[str, str]] = {
    # A successful `action` needs an earlier successful `prior_action` whose
    # prior_key_arg equals the action's key_arg, whose identity_arg equals
    # (case/space-insensitively) the entity's entity_identity_field, and whose
    # result[result_entity_field][result_key_field] equals the key.
    "requires_prior_matching_lookup": {
        "action": "string", "prior_action": "string", "key_arg": "string",
        "prior_key_arg": "string", "identity_arg": "string",
        "entity_collection": "string", "entity_identity_field": "string",
        "result_entity_field": "string", "result_key_field": "string",
    },
    # A successful `action` on an entity whose date_field is missing, or
    # older than window_days before today (exactly window_days still passes).
    "action_within_days_of_entity_date": {
        "action": "string", "key_arg": "string", "entity_collection": "string",
        "date_field": "string", "window_days": "positive_int",
    },
    # Sum of amount_arg over successful `action` calls in one conversation
    # must not exceed cap; reported once, at the crossing call.
    "conversation_total_cap": {
        "action": "string", "amount_arg": "string", "cap": "positive_number",
    },
    # Sum of amount_arg over successful `action` calls grouped by key_arg
    # must not exceed the entity's entity_cap_field; reported once per entity.
    "per_entity_total_cap": {
        "action": "string", "amount_arg": "string", "key_arg": "string",
        "entity_collection": "string", "entity_cap_field": "string",
    },
    # A successful `action` whose argument is one of forbidden_values is a
    # violation (such requests must be escalated instead of actioned).
    "forbidden_action_argument_values": {
        "action": "string", "argument": "string", "forbidden_values": "string_list",
    },
    # The final reply must not contain (case/whitespace-insensitively) any
    # entity's `field` value.
    "never_disclose_entity_field": {
        "entity_collection": "string", "field": "string",
        "lookup_action": "string", "result_entity_field": "string",
        "result_key_field": "string",
    },
}

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_TOP_KEYS = {"version", "provenance", "rules", "uncovered", "informational"}
_PROVENANCE_KEYS = {"model", "policy_sha256", "timestamp", "response_id"}
_RULE_KEYS = {"id", "primitive", "quote", "params"}


@dataclass(frozen=True)
class Rule:
    id: str
    primitive: str
    quote: str
    params: dict[str, Any]


@dataclass(frozen=True)
class Uncovered:
    quote: str
    reason: str


@dataclass(frozen=True)
class Spec:
    version: str
    rules: tuple[Rule, ...]
    provenance: dict[str, Any] = field(default_factory=dict)
    uncovered: tuple[Uncovered, ...] = ()
    informational: tuple[str, ...] = ()


def _check_value(rule_id: str, name: str, value: Any, tag: str) -> None:
    if tag == "string":
        if not isinstance(value, str) or not value.strip():
            raise SpecError(f"rule {rule_id}: param {name!r} must be a non-empty string")
    elif tag == "positive_int":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SpecError(f"rule {rule_id}: param {name!r} must be a positive integer")
    elif tag == "positive_number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise SpecError(f"rule {rule_id}: param {name!r} must be a positive number")
    elif tag == "string_list":
        if (not isinstance(value, list) or not value
                or any(not isinstance(v, str) or not v for v in value)):
            raise SpecError(f"rule {rule_id}: param {name!r} must be a non-empty list of strings")
    else:  # pragma: no cover - internal table bug
        raise AssertionError(tag)


def validate_spec(data: Any, policy_text: str | None = None) -> Spec:
    """Validate raw parsed JSON against the closed DSL; return a Spec."""
    if not isinstance(data, dict):
        raise SpecError("spec must be a JSON object")
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise SpecError(f"unknown top-level keys: {sorted(unknown)}")
    if data.get("version") != SPEC_VERSION:
        raise SpecError(f"spec version must be {SPEC_VERSION!r}")
    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - _PROVENANCE_KEYS:
        raise SpecError("provenance must be an object with only model/policy_sha256/timestamp/response_id")
    for key, value in provenance.items():
        if value is not None and not isinstance(value, str):
            raise SpecError(f"provenance {key!r} must be a string or null")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise SpecError("spec rules must be a non-empty list")
    policy_norm = policy_text.replace("\r\n", "\n") if policy_text is not None else None
    rules: list[Rule] = []
    seen: set[str] = set()
    for raw in raw_rules:
        if not isinstance(raw, dict) or set(raw) - _RULE_KEYS:
            raise SpecError(f"each rule must be an object with only {sorted(_RULE_KEYS)}")
        rid = raw.get("id")
        if not isinstance(rid, str) or not _ID_RE.match(rid):
            raise SpecError(f"rule id must match {_ID_RE.pattern!r}: {rid!r}")
        if rid in seen:
            raise SpecError(f"duplicate rule id: {rid}")
        seen.add(rid)
        primitive = raw.get("primitive")
        if primitive not in PRIMITIVES:
            raise SpecError(f"rule {rid}: unknown primitive: {primitive!r}")
        quote = raw.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise SpecError(f"rule {rid}: missing quote (every rule needs a verbatim policy quote)")
        if policy_norm is not None and quote not in policy_norm:
            raise SpecError(f"rule {rid}: quote is not verbatim in the policy text")
        params = raw.get("params")
        if not isinstance(params, dict):
            raise SpecError(f"rule {rid}: params must be an object")
        expected = PRIMITIVES[primitive]
        if set(params) != set(expected):
            raise SpecError(
                f"rule {rid}: params for {primitive} must be exactly {sorted(expected)}, got {sorted(params)}")
        for name, tag in expected.items():
            _check_value(rid, name, params[name], tag)
        rules.append(Rule(id=rid, primitive=primitive, quote=quote, params=dict(params)))
    uncovered: list[Uncovered] = []
    raw_uncovered = data.get("uncovered", [])
    if not isinstance(raw_uncovered, list):
        raise SpecError("uncovered must be a list of {quote, reason} objects")
    for raw in raw_uncovered:
        if not isinstance(raw, dict) or set(raw) - {"quote", "reason"} or set(raw) != {"quote", "reason"}:
            raise SpecError("each uncovered entry must be an object with only quote and reason")
        uquote = raw.get("quote")
        if not isinstance(uquote, str) or not uquote.strip():
            raise SpecError("uncovered entry: missing quote (every entry needs a verbatim policy quote)")
        if policy_norm is not None and uquote not in policy_norm:
            raise SpecError("uncovered entry: quote is not verbatim in the policy text")
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise SpecError("uncovered entry: reason must be a short non-empty string")
        uncovered.append(Uncovered(quote=uquote, reason=reason))
    informational: list[str] = []
    raw_informational = data.get("informational", [])
    if not isinstance(raw_informational, list):
        raise SpecError("informational must be a list of verbatim policy sentences")
    for item in raw_informational:
        if not isinstance(item, str) or not item.strip():
            raise SpecError("each informational entry must be a verbatim policy sentence")
        if policy_norm is not None and item not in policy_norm:
            raise SpecError("informational entry: quote is not verbatim in the policy text")
        informational.append(item)
    return Spec(version=SPEC_VERSION, rules=tuple(rules), provenance=dict(provenance),
                uncovered=tuple(uncovered), informational=tuple(informational))


def spec_to_dict(spec: Spec) -> dict[str, Any]:
    out: dict[str, Any] = {"version": spec.version}
    if spec.provenance:
        out["provenance"] = dict(spec.provenance)
    out["rules"] = [
        {"id": r.id, "primitive": r.primitive, "quote": r.quote, "params": dict(r.params)}
        for r in spec.rules
    ]
    if spec.uncovered:
        out["uncovered"] = [{"quote": u.quote, "reason": u.reason} for u in spec.uncovered]
    if spec.informational:
        out["informational"] = list(spec.informational)
    return out


def _json_type(tag: str) -> dict[str, Any]:
    return {
        "string": {"type": "string", "minLength": 1},
        "positive_int": {"type": "integer", "exclusiveMinimum": 0},
        "positive_number": {"type": "number", "exclusiveMinimum": 0},
        "string_list": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}},
    }[tag]


def json_schema() -> dict[str, Any]:
    """JSON Schema for the spec the compiler asks the model to emit."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "rules"],
        "properties": {
            "version": {"const": SPEC_VERSION},
            "provenance": {
                "type": "object", "additionalProperties": False,
                "properties": {k: {"type": ["string", "null"]} for k in sorted(_PROVENANCE_KEYS)},
            },
            "informational": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "uncovered": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["quote", "reason"],
                    "properties": {"quote": {"type": "string", "minLength": 1},
                                     "reason": {"type": "string", "minLength": 1}},
                },
            },
            "rules": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["id", "primitive", "quote", "params"],
                    "properties": {
                        "id": {"type": "string", "pattern": _ID_RE.pattern},
                        "primitive": {"enum": sorted(PRIMITIVES)},
                        "quote": {"type": "string", "minLength": 1},
                        "params": {
                            "type": "object",
                            "description": "Exactly the params of the chosen primitive: "
                                           + "; ".join(
                                               f"{name}({', '.join(f'{p}: {t}' for p, t in params.items())})"
                                               for name, params in sorted(PRIMITIVES.items())),
                        },
                    },
                },
            },
        },
    }
