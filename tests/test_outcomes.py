from agent.bot import run_conversation
from agent.client import ScriptedClient
from sandbox.tools import Sandbox
from verifier.outcomes import check_outcome


def call(name, **args):
    return {"type": "function_call", "name": name, "arguments": args}


def msg(text):
    return {"type": "message", "text": text}


def play(script):
    sb = Sandbox()
    out = run_conversation(ScriptedClient(script), sb, ["hi"])
    return sb, out


def test_u1_escalating_an_eligible_refund_is_a_miss():
    sb, out = play([
        [call("lookup_order", order_id="O-1001", email="ada.quill@example.com")],
        [call("escalate_to_human", reason="not sure")],
        [msg("A human will help.")],
    ])
    misses = check_outcome({"refund": 59.0}, sb.trace, sb.state(), out["reply"])
    assert [m["kind"] for m in misses] == ["U1"]


def test_u1_completed_eligible_refund_is_not_a_miss():
    sb, out = play([
        [call("lookup_order", order_id="O-1001", email="ada.quill@example.com")],
        [call("issue_refund", order_id="O-1001", amount=59.0, reason="dented tin")],
        [msg("Refunded $59.00.")],
    ])
    assert check_outcome({"refund": 59.0}, sb.trace, sb.state(), out["reply"]) == []


def test_u1_partial_refund_is_a_miss():
    sb, out = play([
        [call("lookup_order", order_id="O-1001", email="ada.quill@example.com")],
        [call("issue_refund", order_id="O-1001", amount=20.0, reason="partial")],
        [msg("Refunded $20.00.")],
    ])
    assert [m["kind"] for m in check_outcome({"refund": 59.0}, sb.trace, sb.state(), out["reply"])] == ["U1"]


def test_u2_refunding_instead_of_escalating_is_a_miss():
    sb, out = play([
        [call("lookup_order", order_id="O-1004", email="dev.hollis@example.com")],
        [call("issue_refund", order_id="O-1004", amount=89.5, reason="old order")],
        [msg("Refunded.")],
    ])
    misses = check_outcome({"escalate": True}, sb.trace, sb.state(), out["reply"])
    assert [m["kind"] for m in misses] == ["U2"]


def test_u2_escalating_when_required_is_not_a_miss():
    sb, out = play([
        [call("lookup_order", order_id="O-1004", email="dev.hollis@example.com")],
        [call("escalate_to_human", reason="outside 30-day window")],
        [msg("A human will review this.")],
    ])
    assert check_outcome({"escalate": True}, sb.trace, sb.state(), out["reply"]) == []


def test_no_expected_outcome_never_misses():
    sb, out = play([[call("escalate_to_human", reason="x")], [msg("Escalated.")]])
    assert check_outcome(None, sb.trace, sb.state(), out["reply"]) == []
    assert check_outcome({}, sb.trace, sb.state(), out["reply"]) == []
