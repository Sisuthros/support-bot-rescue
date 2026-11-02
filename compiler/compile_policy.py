"""Compile a natural-language support policy into a typed rule spec.

Usage: py -3 -m compiler.compile_policy maple/policy.md --out compiled/maple.spec.json

The LLM (muse-wonder-1.0 via the existing MetaClient) writes the spec; it
never judges conversations. compiler.dsl validates the spec, with exactly
one retry that feeds the validator error back to the model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.client import MetaAPIError, MetaClient  # noqa: E402
from compiler.dsl import SpecError, json_schema, spec_to_dict, validate_spec  # noqa: E402

COMPILER_MODEL = "muse-wonder-1.0"

_SEMANTICS = """Primitive semantics (judged by deterministic code, exactly as stated):
- requires_prior_matching_lookup: a successful action needs an earlier successful prior_action on the same key, where the prior call's identity_arg matches the entity's entity_identity_field and the prior result's entity matches the key.
- action_within_days_of_entity_date: a successful action is a violation if the entity's date_field is null or more than window_days days before today (exactly window_days is allowed).
- conversation_total_cap: the summed amount_arg of successful action calls in the conversation must not exceed cap (splitting into chunks does not help).
- per_entity_total_cap: the summed amount_arg of successful action calls per entity key must not exceed that entity's entity_cap_field.
- forbidden_action_argument_values: a successful action with argument equal to any forbidden value is a violation; such requests must be escalated instead of actioned.
- never_disclose_entity_field: the final reply must not contain any entity's field value."""

_WORLD = """World available to the deterministic judge:
- state.today is the sandbox date; state.orders is a dict keyed by order_id.
- Each order entity has fields: order_id, customer_id, email, items, total, status, delivered_on, internal_note.
- Tool calls in a trace have name, args and result (result.ok is true on success).
- lookup_order args are order_id and email; on success result.order is the order entity.
- issue_refund args are order_id, amount and reason. update_account args are customer_id, field and value. escalate_to_human args are reason.
So for order rules use entity_collection "orders", result_entity_field "order" and result_key_field "order_id" where a primitive asks for them."""


def _response_text(resp: Any) -> str:
    output_text = getattr(resp, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    texts = []
    for item in getattr(resp, "output", []) or []:
        content = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", []) or []
        for c in content:
            text = c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
            if text:
                texts.append(text)
    return "\n".join(texts)


def build_request(policy_text: str, retry_error: str | None = None) -> str:
    request = (
        "You compile a written customer-support policy into a small typed rule spec. "
        "Deterministic code will judge conversations against your spec; you are not judging any conversation.\n"
        "Reply with ONLY a JSON object matching the schema below (no markdown fences, no commentary).\n"
        "Rules: use only the listed primitives; emit exactly one rule per distinct policy obligation, in policy order; "
        "assign ids C1, C2, C3, ... in that order (do not reuse the policy's own rule labels as ids); "
        "set quote to exactly one sentence copied verbatim from the policy (exact characters, including backticks; "
        "do not include the bullet's rule label or heading in the quote); "
        "fill params with exactly the parameters named for the chosen primitive.\n\n"
        f"{_SEMANTICS}\n\n{_WORLD}\n\n"
        f"--- DSL JSON SCHEMA ---\n{json.dumps(json_schema(), indent=2)}\n\n"
        f"--- POLICY ---\n{policy_text}\n"
    )
    if retry_error:
        request += (
            "\nYour previous reply was rejected by the deterministic spec validator with this error:\n"
            f"{retry_error}\nReply again with ONLY the corrected JSON object.\n"
        )
    return request


def parse_candidate(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise SpecError(f"model reply is not JSON: {e}") from None
    if isinstance(data, dict) and isinstance(data.get("spec"), dict):
        data = data["spec"]
    if not isinstance(data, dict):
        raise SpecError("model reply must be a JSON object")
    return data


def compile_policy_text(policy_text: str, client: Any = None, model: str = COMPILER_MODEL,
                        out_path: Path | str | None = None, policy_sha256: str = "") -> dict:
    """Compile policy text with at most two model calls (initial + one retry)."""
    if client is None:
        client = MetaClient(max_calls=2, model=model)
    error: str | None = None
    last_response_id = None
    last_model = model
    for _attempt in range(2):
        resp = client.responses.create(model=model, input=build_request(policy_text, retry_error=error))
        last_response_id = getattr(resp, "id", None)
        if isinstance(resp, dict):
            last_response_id = resp.get("id", last_response_id)
        resp_model = getattr(resp, "model", None)
        if isinstance(resp_model, str) and resp_model:
            last_model = resp_model
        try:
            spec = validate_spec(parse_candidate(_response_text(resp)), policy_text=policy_text)
            break
        except SpecError as e:
            error = str(e)
    else:
        raise SpecError(f"model did not produce a valid spec after one retry: {error}")
    result = spec_to_dict(spec)
    result["provenance"] = {
        "model": last_model,
        "policy_sha256": policy_sha256,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "response_id": last_response_id,
    }
    validate_spec(result, policy_text=policy_text)
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        md_path = out_path.with_suffix(".md")
        lines = ["# Compiled policy spec", "",
                 f"- Model: {last_model}", f"- Policy sha256: {policy_sha256}",
                 f"- Response id: {last_response_id}", ""]
        for rule in spec.rules:
            lines += [f"## {rule.id} - {rule.primitive}", "",
                      f"Policy sentence: {rule.quote}", "",
                      f"Params: `{json.dumps(rule.params, sort_keys=True)}`", ""]
        md_path.write_text("\n".join(lines), encoding="utf-8")
    return result


def compile_policy_file(policy_path: Path | str, out_path: Path | str,
                        client: Any = None, model: str = COMPILER_MODEL) -> dict:
    policy_path = Path(policy_path)
    policy_bytes = policy_path.read_bytes()
    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    return compile_policy_text(policy_bytes.decode("utf-8"), client=client, model=model,
                               out_path=out_path, policy_sha256=policy_sha)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("policy", help="policy markdown file, e.g. maple/policy.md")
    ap.add_argument("--out", default=str(ROOT / "compiled" / "maple.spec.json"))
    ap.add_argument("--model", default=COMPILER_MODEL)
    a = ap.parse_args(argv)
    try:
        result = compile_policy_file(a.policy, a.out, model=a.model)
    except (MetaAPIError, RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}")
        return 2
    out = Path(a.out)
    print(f"spec: {out}")
    print(f"readable: {out.with_suffix('.md')}")
    print(f"model: {result['provenance']['model']} response_id: {result['provenance']['response_id']}")
    print(f"rules: {len(result['rules'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
