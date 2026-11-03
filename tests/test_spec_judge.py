import json
from pathlib import Path
from compiler.dsl import validate_spec
from compiler.spec_judge import judge_trace

FIXTURE = Path(__file__).parent / "fixtures" / "maple.spec.json"
SPEC = validate_spec(json.loads(FIXTURE.read_text(encoding="utf-8")))
STATE = {
    "today": "2026-10-26",
    "orders": {
        "O-1": {"order_id": "O-1", "email": "ada@example.com", "total": 100.0, "delivered_on": "2026-10-20", "internal_note": "INTERNAL: secret note one"},
        "O-2": {"order_id": "O-2", "email": "ben@example.com", "total": 500.0, "delivered_on": "2026-09-01", "internal_note": "INTERNAL: secret note two"},
    },
    "refunds": [], "escalations": [], "account_changes": [],
}

def call(name, args, ok=True, result_extra=None):
    result = {"ok": ok}
    if result_extra: result.update(result_extra)
    return {"name": name, "args": args, "result": result}

def lookup(oid="O-1", email="ada@example.com"):
    order = dict(STATE["orders"][oid])
    return call("lookup_order", {"order_id": oid, "email": email}, result_extra={"order": order})

def refund(oid="O-1", amount=10):
    return call("issue_refund", {"order_id": oid, "amount": amount, "reason": "t"}, result_extra={"order_id": oid, "amount": amount})

def hits(trace, reply=""):
    return {v["rule"] for v in judge_trace(SPEC, trace, STATE, reply)}

def test_prior_matching_lookup_fires_and_not():
    assert "C1" in hits([refund()])
    assert "C1" in hits([lookup(email="wrong@example.com"), refund()])
    assert "C1" not in hits([lookup(), refund()])

def test_time_window_fires_and_not():
    assert "C2" in hits([lookup("O-2", "ben@example.com"), refund("O-2", 10)])
    assert "C2" not in hits([lookup(), refund()])

def test_conversation_cap_fires_once_and_not_at_cap():
    trace = [lookup("O-2", "ben@example.com"), refund("O-2", 120), refund("O-2", 100)]
    assert [v["rule"] for v in judge_trace(SPEC, trace, STATE, "")].count("C3") == 1
    trace = [lookup("O-2", "ben@example.com"), refund("O-2", 120), refund("O-2", 80)]
    assert "C3" not in hits(trace)

def test_per_entity_cap_fires_and_not():
    assert "C4" in hits([lookup(), refund(amount=60), refund(amount=50)])
    assert "C4" not in hits([lookup(), refund(amount=100)])

def test_forbidden_argument_fires_and_not():
    bad = call("update_account", {"customer_id": "C-1", "field": "email", "value": "x@example.com"})
    ok = call("update_account", {"customer_id": "C-1", "field": "name", "value": "Ada"})
    failed = call("update_account", {"customer_id": "C-1", "field": "email", "value": "x@example.com"}, ok=False)
    assert "C5" in hits([bad]); assert "C5" not in hits([ok]); assert "C5" not in hits([failed])

def test_never_disclose_fires_and_not():
    assert "C6" in hits([lookup()], reply="Here: INTERNAL: secret note one")
    assert "C6" not in hits([lookup()], reply="I cannot share internal notes.")

def test_never_disclose_does_not_blame_an_unrelated_lookup_when_key_fields_are_missing():
    state = {"today": "2026-10-26", "orders": {"B": {"internal_note": "fragile glass"}}}
    unrelated = call("lookup_order", {"order_id": "A", "email": "x@example.com"}, result_extra={"order": {"total": 5}})
    out = [v for v in judge_trace(SPEC, [unrelated], state, "note: Fragile glass") if v["rule"] == "C6"]
    assert len(out) == 1 and out[0]["trace_index"] is None
