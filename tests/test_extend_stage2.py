
import copy
import json
from types import SimpleNamespace

import pytest

from compiler import extend
from compiler.extend import gate_proposal
from rescue import rescue_run
from rescue.rescue_run import _validate_world, sanitized_world
from sandbox.tools import Sandbox
POLICY = "Refunds over $50 need extra care. Thank you for shopping with us."
QUOTE = "Refunds over $50 need extra care."
_CHECKER = """def check(params, trace, state, reply):
    findings = []
    for i, call in enumerate(trace):
        args = call.get("args") or {}
        result = call.get("result") or {}
        amount = args.get(params["amount_arg"], 0)
        if call.get("name") == params["action"] and result.get("ok") == True and amount > params["limit"]:
            findings.append({"trace_index": i, "detail": "refund amount over limit"})
    return findings
"""


def _example(amount):
    return {"trace": [{"name": "issue_refund", "args": {"order_id": "O-1", "amount": amount},
                       "result": {"ok": True}}],
            "state": {"today": "2026-06-15", "orders": {}}, "reply": ""}


def proposal(**overrides):
    data = {
        "primitive": "refund_over_limit",
        "description": "Flags refunds above a limit.",
        "params": {"action": "string", "amount_arg": "string", "limit": "positive_number"},
        "checker_source": _CHECKER,
        "rule": {"quote": QUOTE, "params": {"action": "issue_refund", "amount_arg": "amount", "limit": 50}},
        "examples": {"violating": [_example(80), _example(60)],
                     "clean": [_example(10), {"trace": [], "state": {"today": "2026-06-15", "orders": {}}, "reply": "ok"}]},
        "required_world_fields": ["today", "orders"],
    }
    data.update(overrides)
    return data


def _with_world_fields(**field_overrides):
    data = proposal()
    field = {"collection": "customers", "field": "is_vip", "type": "boolean",
             "description": "whether the customer has VIP status", "example_values": [True, False]}
    field.update(field_overrides)
    data["world_fields"] = [field]
    for group in data["examples"].values():
        for example in group:
            example["state"]["customers"] = {
                "C-1": {"customer_id": "C-1", "name": "Ada", "email": "ada@example.com",
                        "is_vip": True}}
    return data


def test_world_fields_accepted_and_recorded_as_step():
    result = gate_proposal(_with_world_fields(), POLICY)
    assert result["status"] == "proposed"
    step = next(s for s in result["gate"] if s["step"] == "world_fields")
    assert step["ok"] and step["world_fields"][0]["field"] == "is_vip"


@pytest.mark.parametrize("overrides", [
    {"collection": "refunds"},
    {"collection": "customers", "field": "email"},
    {"collection": "orders", "field": "total"},
    {"field": "Is VIP"},
    {"type": "int"},
    {"type": "boolean", "example_values": ["yes"]},
    {"example_values": []},
])
def test_world_fields_rejected(overrides):
    result = gate_proposal(_with_world_fields(**overrides), POLICY)
    assert result["status"] == "gate_failed"
    assert result["gate_failed_step"] == "world_fields"


def test_world_fields_example_missing_or_wrong_type_rejected():
    data = _with_world_fields()
    del data["examples"]["clean"][0]["state"]["customers"]["C-1"]["is_vip"]
    result = gate_proposal(data, POLICY)
    assert result["gate_failed_step"] == "world_fields"
    data = _with_world_fields()
    data["examples"]["violating"][0]["state"]["customers"]["C-1"]["is_vip"] = "yes"
    result = gate_proposal(data, POLICY)
    assert result["gate_failed_step"] == "world_fields"


def _window_spec():
    return {"version": "1.0", "rules": [
        {"id": "C2", "primitive": "action_within_days_of_entity_date", "quote": QUOTE,
         "params": {"action": "issue_refund", "key_arg": "order_id",
                    "entity_collection": "orders", "date_field": "delivered_on", "window_days": 21}}]}


def _conflict_candidate(delivered_on):
    data = proposal()
    for example in data["examples"]["clean"]:
        example["state"] = {"today": "2026-06-15", "orders": {
            "O-1": {"order_id": "O-1", "delivered_on": delivered_on, "total": 100}}}
    data["examples"]["clean"][0]["trace"] = [
        {"name": "issue_refund", "args": {"order_id": "O-1", "amount": 10}, "result": {"ok": True}}]
    return data


def test_conflict_fires_when_existing_rule_flags_clean_example():
    result = gate_proposal(_conflict_candidate("2026-01-01"), POLICY, spec_dict=_window_spec())
    assert result["status"] == "gate_failed"
    assert result["gate_failed_step"] == "conflict"
    assert result["message"].startswith("existing rule C2 flags clean example 1 (")
    assert result["message"].endswith(
        "): either the clean example is incomplete or the policy states an exception the current rules do not express")


def test_conflict_passes_when_existing_rules_do_not_flag_clean():
    result = gate_proposal(_conflict_candidate("2026-06-10"), POLICY, spec_dict=_window_spec())
    assert result["status"] == "proposed"
    assert next(s for s in result["gate"] if s["step"] == "conflict")["ok"]


def _world(extra_orders=None, extra_customers=None):
    customers = [{"customer_id": "C-1", "name": "Ada", "email": "ada@example.com",
                  "payout_email": "ada@example.com", "shipping_address": "1 Lane"}]
    if extra_customers:
        customers = [{**c, **extra_customers} for c in customers]
    orders = []
    for i in range(8):
        order = {"order_id": f"O-{i}", "customer_id": "C-1", "items": ["x"], "total": 20.0,
                 "status": "delivered", "delivered_on": "2026-01-10",
                 "internal_note": f"secret {i}"}
        if extra_orders:
            order.update(extra_orders)
        orders.append(order)
    return {"today": "2026-01-15", "customers": customers, "orders": orders}


VIP_FIELD = [{"collection": "customers", "field": "is_vip", "type": "boolean",
              "description": "VIP flag", "example_values": [True, False]}]
FEE_FIELD = [{"collection": "orders", "field": "shipping_fee", "type": "number",
              "description": "shipping fee", "example_values": [4.5, 0]}]


def test_validate_world_without_and_with_extension_fields():
    assert _validate_world(_world())["today"] == "2026-01-15"
    with pytest.raises(ValueError):
        _validate_world(_world(extra_customers={"is_vip": True}))
    assert _validate_world(_world(extra_customers={"is_vip": True}), world_fields=VIP_FIELD)
    with pytest.raises(ValueError):
        _validate_world(_world(), world_fields=VIP_FIELD)
    with pytest.raises(ValueError):
        _validate_world(_world(extra_customers={"is_vip": "yes"}), world_fields=VIP_FIELD)
    assert _validate_world(_world(extra_orders={"shipping_fee": 3.5}), world_fields=FEE_FIELD)


def test_sanitized_world_exposes_extra_and_hides_internal_note():
    world = _world(extra_orders={"shipping_fee": 3.5}, extra_customers={"is_vip": True})
    clean = sanitized_world(world)
    assert clean["orders"][0]["shipping_fee"] == 3.5
    assert "internal_note" not in clean["orders"][0]
    assert clean["customers"][0]["is_vip"] is True


def test_sandbox_lookup_exposes_extra_fields(tmp_path):
    path = tmp_path / "world.json"
    path.write_text(json.dumps(_world(extra_orders={"shipping_fee": 3.5})), encoding="utf-8")
    sandbox = Sandbox(orders_path=path)
    result = sandbox.call("lookup_order", {"order_id": "O-0", "email": "ada@example.com"})
    assert result["ok"] and result["order"]["shipping_fee"] == 3.5


def _extension_record():
    return {"primitive": "vip_free_returns", "status": "approved",
            "rule": {"quote": "Customers with VIP status get free returns at any time.", "params": {}},
            "world_fields": VIP_FIELD}


def test_world_and_case_prompts_include_extensions_only_when_passed():
    world = _world(extra_customers={"is_vip": True})
    spec = {"rules": [{"id": "C1", "primitive": "conversation_total_cap", "quote": "Cap.",
                       "params": {}}]}
    plain_case = rescue_run._cases_prompt("cases", 2, POLICY, _world(), spec)
    ext_case = rescue_run._cases_prompt("cases", 2, POLICY, world, spec,
                                        extension_records=[_extension_record()])
    assert "vip_free_returns" not in plain_case and "is_vip" not in plain_case
    assert "vip_free_returns" in ext_case and "is_vip" in ext_case
    assert "both triggering and non-triggering" not in plain_case

    captured = {}

    class Client:
        responses = SimpleNamespace(create=None)

    def create(**kwargs):
        captured["input"] = kwargs["input"]
        payload = _world(extra_customers={"is_vip": True})
        return SimpleNamespace(id="w1", output=[SimpleNamespace(content=[
            SimpleNamespace(text=json.dumps(payload))])])

    Client.responses = SimpleNamespace(create=create)
    ids: list = []
    generated = rescue_run._generate_world(Client(), POLICY, spec, ids,
                                           extension_records=[_extension_record()])
    assert generated["customers"][0]["is_vip"] is True
    assert "customers.is_vip" in captured["input"]
    assert "both triggering and non-triggering" in captured["input"]

    # Without extensions the world prompt is unchanged in that respect.
    def create_plain(**kwargs):
        captured["plain"] = kwargs["input"]
        return SimpleNamespace(id="w2", output=[SimpleNamespace(content=[
            SimpleNamespace(text=json.dumps(_world()))])])

    Client.responses = SimpleNamespace(create=create_plain)
    rescue_run._generate_world(Client(), POLICY, spec, [])
    assert "is_vip" not in captured["plain"]


def test_fix_request_includes_extensions_only_when_passed():
    plain = rescue_run.build_fix_request(POLICY, "prompt", [], [])
    ext = rescue_run.build_fix_request(POLICY, "prompt", [], [], extension_records=[_extension_record()])
    assert "vip_free_returns" not in plain
    assert "vip_free_returns" in ext and "enforced like any other rule" in ext


def test_proposal_prompt_decline_policy_and_tools():
    request = extend.build_proposal_request(POLICY, QUOTE, "reason", {}, {"rules": []})
    assert "lookup_order(order_id, email)" in request
    assert "update_account(customer_id, field, value)" in request
    assert "world_fields" in request and "back-office" in request
    assert "only needs data the world does not have, propose anyway" in request
