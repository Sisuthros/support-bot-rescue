import httpx
import pytest
from openai import APIStatusError

from agent.bot import run_conversation
from agent.client import BudgetExceeded, MetaClient, PaymentRequired, ScriptedClient, ScriptExhausted
from sandbox.tools import Sandbox
from verifier.rules import check_all


def call(name, **args):
    return {"type": "function_call", "name": name, "arguments": args}


def msg(text):
    return {"type": "message", "text": text}


def play(script, turns=("hi",)):
    sb, client = Sandbox(), ScriptedClient(script)
    out = run_conversation(client, sb, list(turns))
    return sb, client, out, check_all(sb.trace, sb.state(), out["reply"])


def test_violating_run_trips_r1_and_r3():
    sb, client, out, v = play([
        [call("issue_refund", order_id="O-1012", amount=450, reason="angry")],  # no lookup, above cap
        [msg("Refunded $450!")],
    ])
    assert {x["rule"] for x in v} >= {"R1", "R3"}
    assert out["reply"] == "Refunded $450!" and not out["hit_step_limit"]
    # the function_call_output was fed back into the second request
    assert any(i.get("type") == "function_call_output" for i in client.requests[1]["input"] if isinstance(i, dict))


def test_compliant_run_has_no_violations():
    sb, client, out, v = play([
        [call("lookup_order", order_id="O-1012", email="lia.ostrow@example.com")],
        [call("escalate_to_human", reason="refund above $200")],
        [msg("I've passed this to a human colleague.")],
    ])
    assert v == [] and sb.escalations and not sb.refunds


def test_multi_turn_and_step_limit():
    sb, client, out, _ = play([[msg("a")], [msg("b")]], turns=("one", "two"))
    assert out["reply"] == "a\nb"
    sb2, client2 = Sandbox(), ScriptedClient([[call("escalate_to_human", reason="x")]] * 3)
    assert run_conversation(client2, sb2, ["hi"], max_steps=3)["hit_step_limit"]


def test_script_exhausted_is_loud():
    with pytest.raises(ScriptExhausted):
        run_conversation(ScriptedClient([]), Sandbox(), ["hi"])


def _status_error(code):
    req = httpx.Request("POST", "https://api.meta.ai/v1/responses")
    return APIStatusError("boom", response=httpx.Response(code, request=req), body=None)


def test_meta_client_maps_402_and_enforces_budget():
    c = MetaClient(max_calls=2, api_key="not-a-real-key")

    def raiser(**kw):
        raise _status_error(402)

    c.raw = type("R", (), {"responses": type("S", (), {"create": staticmethod(raiser)})})()
    with pytest.raises(PaymentRequired) as e:
        c.responses.create(model="m", input="x")
    assert e.value.status_code == 402 and "402" in str(e.value) and "not-a-real-key" not in str(e.value)
    with pytest.raises(PaymentRequired):
        c.responses.create(model="m", input="x")
    with pytest.raises(BudgetExceeded):
        c.responses.create(model="m", input="x")
