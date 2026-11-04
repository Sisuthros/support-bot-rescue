"""Closed, typed rule vocabulary for compiled support policies.

The LLM may only emit rules using the primitives below. Plain code
(:mod:`compiler.spec_judge`) interprets them; anything outside this
vocabulary is rejected here, before any judging happens.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
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
_TOP_KEYS = {"version", "provenance", "rules", "uncovered", "informational", "extensions"}
_PROVENANCE_KEYS = {"model", "policy_sha256", "timestamp", "response_id", "extensions"}
_EXTENSION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PARAM_TYPE_TAGS = {"string", "positive_int", "positive_number", "string_list"}
_RULE_KEYS = {"id", "primitive", "quote", "params"}


@dataclass(frozen=True)
class Rule:
    id: str
    primitive: str
    quote: str
    params: dict[str, Any]


@dataclass(frozen=True)
class Extension:
    """An approved extension primitive (approver recorded in the proposal), with its gated checker source."""

    name: str
    params: dict[str, str]
    checker_source: str
    checker_sha256: str
    approval: dict[str, Any]
    description: str = ""


def checker_sha256(checker_source: str) -> str:
    """Return the sha256 approval is bound to for a checker source string."""
    return hashlib.sha256(checker_source.encode("utf-8")).hexdigest()


def _coerce_extension(raw: Any, key_hint: str | None = None) -> Extension:
    if isinstance(raw, Extension):
        if checker_sha256(raw.checker_source) != raw.checker_sha256:
            raise SpecError(f"extension {raw.name!r}: checker sha256 does not match its approval")
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("proposal"), dict):
        merged = dict(raw["proposal"])
        for key, value in raw.items():
            if key != "proposal":
                merged[key] = value
        raw = merged
    if not isinstance(raw, dict):
        raise SpecError("extension must be an approved proposal object")
    name = raw.get("primitive") or raw.get("name") or key_hint
    if not isinstance(name, str) or not _EXTENSION_NAME_RE.match(name):
        raise SpecError(f"extension primitive name must be snake_case: {name!r}")
    if name in PRIMITIVES:
        raise SpecError(f"extension {name!r} collides with a built-in primitive")
    schema = raw.get("params")
    if not isinstance(schema, dict) or any(not isinstance(k, str) or v not in PARAM_TYPE_TAGS for k, v in schema.items()):
        raise SpecError(f"extension {name!r}: params must map names to DSL type tags")
    source = raw.get("checker_source")
    if not isinstance(source, str) or not source.strip():
        raise SpecError(f"extension {name!r}: checker_source must be a non-empty string")
    status = raw.get("status")
    if status is not None and status != "approved":
        raise SpecError(f"extension {name!r} is not approved (status={status!r})")
    approval = raw.get("approval")
    if not isinstance(approval, dict):
        raise SpecError(f"extension {name!r} is not approved: missing approval record")
    by = approval.get("by")
    timestamp = approval.get("timestamp") or approval.get("approved_at")
    approved_sha = approval.get("checker_sha256") or approval.get("checker_sha") or approval.get("sha256")
    if not isinstance(by, str) or not by.strip() or not isinstance(timestamp, str) or not timestamp.strip():
        raise SpecError(f"extension {name!r} is not approved: approval needs by and timestamp")
    actual_sha = checker_sha256(source)
    if approved_sha != actual_sha:
        raise SpecError(
            f"extension {name!r}: checker sha256 {actual_sha} does not match approved sha256 {approved_sha!r}")
    description = raw.get("description")
    return Extension(name=name, params=dict(schema), checker_source=source,
                     checker_sha256=actual_sha,
                     approval={"by": by, "timestamp": timestamp, "checker_sha256": actual_sha},
                     description=description if isinstance(description, str) else "")


def _extension_records(source: Any) -> tuple[list[Any], bool]:
    """Return (records, came_from_directory); directories skip unapproved files."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_dir():
            records: list[Any] = []
            for file in sorted(path.glob("*.json")):
                try:
                    record = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise SpecError(f"cannot read extension proposal {file}: {exc}") from None
                if isinstance(record, dict) and record.get("status") == "approved":
                    records.append(record)
                elif isinstance(record, dict) and isinstance(record.get("approval"), dict):
                    records.append(record)
            return records, True
        if path.is_file():
            try:
                return [json.loads(path.read_text(encoding="utf-8"))], False
            except (OSError, json.JSONDecodeError) as exc:
                raise SpecError(f"cannot read extension proposal {path}: {exc}") from None
    return [source], False


def extension_map(extensions: Any = None) -> dict[str, Extension]:
    """Normalise approved extensions from records, mappings, lists, or a directory.

    Directly supplied records must be approved and their checker sha256 must
    match the approval. A proposals directory contributes only its approved
    records (proposed/declined/gate_failed files are skipped, but a tampered
    approved record is rejected).
    """
    if extensions is None:
        return {}
    records: list[tuple[Any, str | None]] = []
    if isinstance(extensions, dict) and not any(
            key in extensions for key in ("primitive", "name", "checker_source", "proposal")):
        if isinstance(extensions.get("extensions"), list):
            records = [(item, None) for item in extensions["extensions"]]
        else:
            records = [(value, key if isinstance(key, str) else None)
                       for key, value in extensions.items()]
    elif isinstance(extensions, (list, tuple, set)):
        for item in extensions:
            sub_records, _from_dir = _extension_records(item)
            records.extend((item_record, None) for item_record in sub_records)
    else:
        sub_records, _from_dir = _extension_records(extensions)
        records = [(item, None) for item in sub_records]
    out: dict[str, Extension] = {}
    for raw, hint in records:
        extension = _coerce_extension(raw, key_hint=hint)
        if extension.name in out:
            raise SpecError(f"duplicate extension primitive: {extension.name!r}")
        out[extension.name] = extension
    return out


def load_extensions(source: Any = None) -> dict[str, Extension]:
    """Load approved extensions from a proposals directory or record collection."""
    return extension_map(source)


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
    extensions: dict[str, Extension] = field(default_factory=dict)


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


def validate_spec(data: Any, policy_text: str | None = None, extensions: Any = None) -> Spec:
    """Validate raw parsed JSON against the closed DSL; return a Spec."""
    if not isinstance(data, dict):
        raise SpecError("spec must be a JSON object")
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise SpecError(f"unknown top-level keys: {sorted(unknown)}")
    if data.get("version") != SPEC_VERSION:
        raise SpecError(f"spec version must be {SPEC_VERSION!r}")
    ext_map = extension_map(extensions)
    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict) or set(provenance) - _PROVENANCE_KEYS:
        raise SpecError("provenance must be an object with only model/policy_sha256/timestamp/response_id/extensions")
    for key, value in provenance.items():
        if key == "extensions":
            if not isinstance(value, list) or any(
                    not isinstance(item, dict) or set(item) != {"name", "checker_sha256"}
                    or not isinstance(item.get("name"), str) or not item["name"]
                    or not isinstance(item.get("checker_sha256"), str) or not item["checker_sha256"]
                    for item in value):
                raise SpecError("provenance extensions must be a list of {name, checker_sha256} objects")
            continue
        if value is not None and not isinstance(value, str):
            raise SpecError(f"provenance {key!r} must be a string or null")
    top_extensions = data.get("extensions")
    if top_extensions is not None and (
            not isinstance(top_extensions, list) or any(
                not isinstance(item, dict) or set(item) != {"name", "checker_sha256"}
                or not isinstance(item.get("name"), str) or not item["name"]
                or not isinstance(item.get("checker_sha256"), str) or not item["checker_sha256"]
                for item in top_extensions)):
        raise SpecError("extensions must be a list of {name, checker_sha256} objects")
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
        if primitive not in PRIMITIVES and primitive not in ext_map:
            raise SpecError(f"rule {rid}: unknown primitive: {primitive!r}")
        quote = raw.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            raise SpecError(f"rule {rid}: missing quote (every rule needs a verbatim policy quote)")
        if policy_norm is not None and quote not in policy_norm:
            raise SpecError(f"rule {rid}: quote is not verbatim in the policy text")
        params = raw.get("params")
        if not isinstance(params, dict):
            raise SpecError(f"rule {rid}: params must be an object")
        expected = PRIMITIVES[primitive] if primitive in PRIMITIVES else ext_map[primitive].params
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
                uncovered=tuple(uncovered), informational=tuple(informational),
                extensions=dict(ext_map))


def spec_to_dict(spec: Spec) -> dict[str, Any]:
    out: dict[str, Any] = {"version": spec.version}
    if spec.provenance:
        out["provenance"] = dict(spec.provenance)
    if spec.extensions:
        used = []
        for rule in spec.rules:
            if rule.primitive in spec.extensions and rule.primitive not in used:
                used.append(rule.primitive)
        if used:
            provenance_out = dict(out.get("provenance") or {})
            provenance_out.setdefault("extensions", [
                {"name": name, "checker_sha256": spec.extensions[name].checker_sha256}
                for name in used])
            out["provenance"] = provenance_out
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
