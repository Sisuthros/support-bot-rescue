from sandbox.tools import TOOL_SCHEMAS, Sandbox

EMAIL = "ada.quill@example.com"


def test_lookup_matches_and_mismatches():
    sb = Sandbox()
    ok = sb.call("lookup_order", {"order_id": "O-1001", "email": EMAIL.upper()})
    assert ok["ok"] and ok["order"]["total"] == 59.0 and "internal_note" in ok["order"]
    assert not sb.call("lookup_order", {"order_id": "O-1001", "email": "x@example.com"})["ok"]
    assert not sb.call("lookup_order", {"order_id": "O-9999", "email": EMAIL})["ok"]


def test_refund_escalate_update_are_recorded_in_order():
    sb = Sandbox()
    assert sb.call("issue_refund", {"order_id": "O-1001", "amount": 10, "reason": "x"})["ok"]
    assert sb.call("escalate_to_human", {"reason": "y"})["ok"]
    assert sb.call("update_account", {"customer_id": "C-01", "field": "name", "value": "A. Quill"})["ok"]
    assert [c["name"] for c in sb.trace] == ["issue_refund", "escalate_to_human", "update_account"]
    assert [c["index"] for c in sb.trace] == [0, 1, 2]
    st = sb.state()
    assert st["refunds"][0]["trace_index"] == 0 and st["escalations"] and st["account_changes"]
    assert sb.customers["C-01"]["name"] == "A. Quill"


def test_bad_calls_fail_but_are_traced():
    sb = Sandbox()
    assert not sb.call("issue_refund", {"order_id": "O-1001", "amount": -5, "reason": "x"})["ok"]
    assert not sb.call("issue_refund", {"order_id": "O-1001"})["ok"]
    assert not sb.call("update_account", {"customer_id": "C-01", "field": "password", "value": "x"})["ok"]
    assert not sb.call("rm_rf", {})["ok"]
    assert not sb.call("lookup_order", "not a dict")["ok"]
    assert len(sb.trace) == 5 and not sb.refunds


def test_schemas_use_responses_function_format():
    assert {s["name"] for s in TOOL_SCHEMAS} == {"lookup_order", "issue_refund", "escalate_to_human", "update_account"}
    for s in TOOL_SCHEMAS:
        assert s["type"] == "function" and s["parameters"]["type"] == "object" and "function" not in s
