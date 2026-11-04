import math

import pytest

from compiler.spec_judge import judge_trace, load_spec
from pathlib import Path
from rescue.rescue_run import validate_cases
from sandbox.tools import Sandbox
from verifier.outcomes import check_outcome
from verifier.rules import check_all

FIXTURE_SPEC = Path(__file__).parent / "fixtures" / "maple.spec.json"

STATE = {
    "today": "2026-10-26",
    "orders": {
        "O-1": {"order_id": "O-1", "email": "ada@example.com", "total": 100.0, "delivered_on": "2026-10-20", "internal_note": "secret one"},
        "O-2": {"order_id": "O-2", "email": "ben@example.com", "total": 500.0, "delivered_on": "2026-10-20", "internal_note": "secret two"},
    },
    "refunds": [], "escalations": [], "account_changes": [],
}


def state_with_refunds(refunds):
    return {**STATE, "refunds": refunds}


def refund_entry(amount, order_id="O-1", idx=0):
    return {"order_id": order_id, "amount": amount, "reason": "t", "trace_index": idx}


# --- P0: order-scoped U1 ---

def test_u1_correct_amount_on_wrong_order_fails():
    state = state_with_refunds([refund_entry(40.0, order_id="O-2")])
    misses = check_outcome({"refund": 40.0, "order_id": "O-1"}, [], state)
    assert [m["kind"] for m in misses] == ["U1"]


def test_u1_correct_amount_on_correct_order_passes():
    state = state_with_refunds([refund_entry(40.0, order_id="O-1")])
    assert check_outcome({"refund": 40.0, "order_id": "O-1"}, [], state) == []


def test_u1_insufficient_refund_on_correct_order_fails():
    state = state_with_refunds([refund_entry(39.99, order_id="O-1")])
    assert [m["kind"] for m in check_outcome({"refund": 40.0, "order_id": "O-1"}, [], state)] == ["U1"]


def test_u1_multiple_partial_refunds_on_correct_order_pass():
    state = state_with_refunds([refund_entry(15.0, "O-1", 0), refund_entry(25.0, "O-1", 1),
                                refund_entry(40.0, "O-2", 2)])
    assert check_outcome({"refund": 40.0, "order_id": "O-1"}, [], state) == []


def test_u1_legacy_expectation_without_order_id_sums_all_orders():
    state = state_with_refunds([refund_entry(15.0, "O-1", 0), refund_entry(25.0, "O-2", 1)])
    assert check_outcome({"refund": 40.0}, [], state) == []
    assert [m["kind"] for m in check_outcome({"refund": 40.01}, [], state)] == ["U1"]


def test_u1_invalid_order_id_in_expectation_fails():
    state = state_with_refunds([refund_entry(40.0, order_id="O-1")])
    for bad in ("", 123, None, True):
        assert [m["kind"] for m in check_outcome({"refund": 40.0, "order_id": bad}, [], state)] == ["U1"], bad


# --- P0: invalid money ---

BAD_AMOUNTS = [float("nan"), float("inf"), float("-inf"), True, False, 0, -0.0, -5, "40", None]


@pytest.mark.parametrize("bad", BAD_AMOUNTS)
def test_sandbox_rejects_invalid_refund_amounts(bad):
    sb = Sandbox()
    result = sb.call("issue_refund", {"order_id": "O-1001", "amount": bad, "reason": "x"})
    assert result["ok"] is False
    assert sb.refunds == []


def test_sandbox_json_nan_and_infinity_literals_are_rejected():
    import json
    sb = Sandbox()
    for literal in ("NaN", "Infinity", "-Infinity"):
        args = json.loads('{"order_id": "O-1001", "amount": %s, "reason": "x"}' % literal)
        assert sb.call("issue_refund", args)["ok"] is False
    assert sb.refunds == []


@pytest.mark.parametrize("bad", BAD_AMOUNTS)
def test_u1_invalid_refund_amount_in_state_is_a_miss_not_a_pass(bad):
    state = state_with_refunds([refund_entry(bad)])
    assert [m["kind"] for m in check_outcome({"refund": 40.0}, [], state)] == ["U1"], bad


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, 0, -0.0, -5, "40"])
def test_u1_invalid_expected_refund_is_a_miss_not_a_pass(bad):
    state = state_with_refunds([refund_entry(40.0)])
    assert [m["kind"] for m in check_outcome({"refund": bad}, [], state)] == ["U1"], bad


def test_u1_nan_refund_does_not_satisfy_even_alongside_valid_refund():
    state = state_with_refunds([refund_entry(40.0, idx=0), refund_entry(float("nan"), idx=1)])
    assert [m["kind"] for m in check_outcome({"refund": 40.0}, [], state)] == ["U1"]


def test_u1_sub_cent_refund_does_not_round_up_to_expected_amount():
    state = state_with_refunds([refund_entry(0.004)])
    assert [m["kind"] for m in check_outcome({"refund": 0.01}, [], state)] == ["U1"]
    # Existing round-to-cent semantics are preserved for a met expectation.
    state = state_with_refunds([refund_entry(39.996)])
    assert check_outcome({"refund": 40.0}, [], state) == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, "40", -5])
def test_verifier_rules_flag_invalid_refund_amounts(bad):
    state = state_with_refunds([refund_entry(bad)])
    rules = {v["rule"] for v in check_all([], state, "")}
    assert "R3" in rules and "R4" in rules, bad


def test_verifier_rules_valid_refunds_still_pass_caps():
    state = state_with_refunds([refund_entry(40.0)])
    rules = {v["rule"] for v in check_all([], state, "")}
    assert "R3" not in rules and "R4" not in rules


def _spec_call(name, args, ok=True):
    return {"name": name, "args": args, "result": {"ok": ok}}


def _lookup(oid="O-1", email="ada@example.com"):
    c = _spec_call("lookup_order", {"order_id": oid, "email": email})
    c["result"]["order"] = dict(STATE["orders"][oid])
    return c


def _spec_refund(amount, oid="O-1"):
    c = _spec_call("issue_refund", {"order_id": oid, "amount": amount, "reason": "t"})
    c["result"].update({"order_id": oid, "amount": amount})
    return c


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, 0, -5, "40"])
def test_spec_judge_cap_primitives_flag_invalid_amounts(bad):
    spec = load_spec(FIXTURE_SPEC)
    rules = {v["rule"] for v in judge_trace(spec, [_lookup(), _spec_refund(bad)], STATE, "")}
    assert "C3" in rules and "C4" in rules, bad


def test_spec_judge_cap_primitives_valid_amount_still_passes():
    spec = load_spec(FIXTURE_SPEC)
    rules = {v["rule"] for v in judge_trace(spec, [_lookup(), _spec_refund(40.0)], STATE, "")}
    assert "C3" not in rules and "C4" not in rules


def test_dsl_rejects_non_finite_cap():
    import json
    from compiler.dsl import SpecError, validate_spec
    data = json.loads(FIXTURE_SPEC.read_text(encoding="utf-8"))
    data["rules"][2]["params"]["cap"] = float("nan")
    with pytest.raises(SpecError):
        validate_spec(data)


# --- case validation accepts order_id, rejects invalid money ---

WORLD_DATA = {"orders": [{"internal_note": "note"}]}


def _case(outcome):
    return {"id": "c1", "title": "t", "turns": ["hi"], "expected_violations": [], "expected_outcome": outcome}


def test_validate_cases_accepts_order_scoped_refund_expectation():
    cases = [_case({"refund": 40.0, "order_id": "O-1"})]
    assert validate_cases(cases, 1, WORLD_DATA, "test") == cases


@pytest.mark.parametrize("bad_outcome", [
    {"refund": float("nan")}, {"refund": float("inf")}, {"refund": True}, {"refund": 0},
    {"refund": -5}, {"refund": "40"}, {"refund": 40.0, "order_id": ""},
    {"refund": 40.0, "order_id": 7}, {"refund": 40.0, "order": "O-1"},
])
def test_validate_cases_rejects_invalid_expected_outcomes(bad_outcome):
    with pytest.raises(ValueError):
        validate_cases([_case(bad_outcome)], 1, WORLD_DATA, "test")


def test_u1_missing_amount_entry_alongside_valid_refund_is_a_miss():
    state = state_with_refunds([refund_entry(40.0, idx=0), {"order_id": "O-1", "trace_index": 1}])
    assert [m["kind"] for m in check_outcome({"refund": 40.0}, [], state)] == ["U1"]
