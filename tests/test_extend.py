import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from compiler import extend
from compiler.coverage import compute_coverage
from compiler.dsl import SpecError, validate_spec
from compiler.extend import ProposalError, gate_proposal, validate_checker_ast
from compiler.sandbox_runner import run_checker
from compiler.spec_judge import judge_trace

POLICY = "Refunds over $50 need extra care. Thank you for shopping with us."
QUOTE = "Refunds over $50 need extra care."

CHECKER = """def check(params, trace, state, reply):
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
        "checker_source": CHECKER,
        "rule": {"quote": QUOTE, "params": {"action": "issue_refund", "amount_arg": "amount", "limit": 50}},
        "examples": {"violating": [_example(80), _example(60)],
                     "clean": [_example(10), {"trace": [], "state": {"today": "2026-06-15", "orders": {}}, "reply": "ok"}]},
        "required_world_fields": ["today", "orders"],
    }
    data.update(overrides)
    return data


def _approved_record(tmp_path, name="refund_over_limit"):
    record = proposal(primitive=name)
    record["status"] = "proposed"
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return extend.approve_proposal(path, by="Ada Approver")


def _extension_spec():
    return {"version": "1.0", "rules": [
        {"id": "C1", "primitive": "refund_over_limit", "quote": QUOTE,
         "params": {"action": "issue_refund", "amount_arg": "amount", "limit": 50}}]}


@pytest.mark.parametrize("source", [
    "import os\ndef check(params, trace, state, reply):\n    return []\n",
    "def check(params, trace, state, reply):\n    return state.__dict__\n",
    "def check(params, trace, state, reply):\n    return eval('[]')\n",
    "def check(params, trace, state, reply):\n    while True:\n        return []\n",
    "def check(params, trace, state, reply):\n    open('x')\n    return []\n",
    "def check(params, trace, state, reply):\n    return []\ndef helper(params, trace, state, reply):\n    return []\n",
])
def test_ast_gate_rejects_banned_checkers(source):
    with pytest.raises(ProposalError):
        validate_checker_ast(source)
    result = gate_proposal(proposal(checker_source=source), POLICY)
    assert result["status"] == "gate_failed"
    assert result["gate_failed_step"] in {"json_shape", "ast_whitelist"}


def test_gate_accepts_correct_checker():
    result = gate_proposal(proposal(), POLICY)
    assert result["status"] == "proposed"
    assert [step["step"] for step in result["gate"]] == [
        "json_shape", "ast_whitelist", "sandbox_execution", "self_test", "replay"]
    assert all(step["ok"] for step in result["gate"])


def test_gate_declines_honestly():
    result = gate_proposal({"decline": "the trace cannot show this"}, POLICY)
    assert result["status"] == "declined"


def test_sandbox_times_out_on_huge_for_loop():
    source = ("def check(params, trace, state, reply):\n"
              "    total = 0\n"
              "    for i in range(1000000000):\n"
              "        total = total + i\n"
              "    return []\n")
    with pytest.raises(TimeoutError):
        run_checker(source, {}, [], {}, "")


def test_self_test_fails_checker_that_flags_clean_example():
    bad = proposal(checker_source=CHECKER.replace(
        "amount > params[\"limit\"]", "amount > 0"))
    # Both clean examples have no positive refund except the $10 one; make all flag instead.
    bad["checker_source"] = ("def check(params, trace, state, reply):\n"
                             "    return [{\"trace_index\": None, \"detail\": \"always\"}]\n")
    result = gate_proposal(bad, POLICY)
    assert result["status"] == "gate_failed"
    assert result["gate_failed_step"] == "self_test"
def test_approve_refuses_gate_failed_and_declined(tmp_path):
    for status in ("gate_failed", "declined"):
        path = tmp_path / f"{status}.json"
        path.write_text(json.dumps({"status": status, "checker_source": CHECKER}), encoding="utf-8")
        with pytest.raises(ProposalError, match="refusing to approve"):
            extend.approve_proposal(path, by="Ada")
        assert extend.main(["approve", str(path), "--by", "Ada"]) == 2


def test_validate_spec_rejects_unapproved_extension():
    record = proposal()
    record["status"] = "proposed"
    with pytest.raises(SpecError, match="not approved"):
        validate_spec(_extension_spec(), extensions=[record])


def test_validate_spec_rejects_checker_sha_changed_after_approval(tmp_path):
    record = _approved_record(tmp_path)
    tampered = dict(record)
    tampered["checker_source"] = record["checker_source"] + "\n"
    with pytest.raises(SpecError, match="sha256"):
        validate_spec(_extension_spec(), extensions=[tampered])


def test_validate_and_judge_approved_extension(tmp_path):
    record = _approved_record(tmp_path)
    spec = validate_spec(_extension_spec(), policy_text=POLICY, extensions=[record])
    out = judge_trace(spec, _example(80)["trace"], _example(80)["state"], "")
    assert out == [{"rule": "C1", "trace_index": 0, "detail": "refund amount over limit"}]
    assert judge_trace(spec, _example(10)["trace"], _example(10)["state"], "") == []


def test_coverage_via_extension_and_headline(tmp_path):
    record = _approved_record(tmp_path)
    base = {"version": "1.0",
            "rules": [{"id": "C1", "primitive": "conversation_total_cap", "quote": QUOTE,
                       "params": {"action": "issue_refund", "amount_arg": "amount", "cap": 120}}],
            "uncovered": [{"quote": QUOTE, "reason": "needs a new primitive"}]}
    applied = extend.apply_proposals(base, [record])
    cov = compute_coverage(POLICY, applied)
    entry = next(e for e in cov["sentences"] if e["sentence"] == QUOTE)
    assert entry["label"] == "enforced"
    assert entry["via_extension"] == "refund_over_limit"
    assert cov["headline"].endswith(" (1 via human-approved extensions)")


def test_apply_numbering_and_provenance(tmp_path):
    record = _approved_record(tmp_path)
    base = {"version": "1.0",
            "rules": [
                {"id": "C1", "primitive": "conversation_total_cap", "quote": "Thank you for shopping with us.",
                 "params": {"action": "issue_refund", "amount_arg": "amount", "cap": 120}},
                {"id": "C2", "primitive": "conversation_total_cap", "quote": "Thank you for shopping with us.",
                 "params": {"action": "issue_refund", "amount_arg": "amount", "cap": 90}}],
            "uncovered": [{"quote": QUOTE, "reason": "needs a new primitive"}],
            "provenance": {"model": "muse-wonder-1.0"}}
    applied = extend.apply_proposals(base, [record])
    assert applied["rules"][-1]["id"] == "C3"
    assert applied["rules"][-1]["primitive"] == "refund_over_limit"
    assert applied.get("uncovered", []) == []
    assert applied["provenance"]["extensions"] == [
        {"name": "refund_over_limit", "checker_sha256": record["approval"]["checker_sha256"]}]


class FakeClient:
    def __init__(self, texts):
        self.texts = list(texts)
        self.requests = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        text = self.texts.pop(0)
        return SimpleNamespace(id=f"resp-{len(self.requests)}", model="muse-wonder-1.0",
                               output=[SimpleNamespace(type="message", content=[
                                   SimpleNamespace(type="output_text", text=text)])])


def test_propose_with_fake_client_persists_unapproved_proposal(tmp_path):
    policy = tmp_path / "policy.md"
    policy.write_text(POLICY, encoding="utf-8")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({
        "version": "1.0",
        "rules": [{"id": "C1", "primitive": "conversation_total_cap", "quote": "Thank you for shopping with us.",
                   "params": {"action": "issue_refund", "amount_arg": "amount", "cap": 120}}],
        "uncovered": [{"quote": QUOTE, "reason": "no built-in expresses a per-refund limit"}]}),
        encoding="utf-8")
    client = FakeClient([json.dumps(proposal())])
    records = extend.propose(policy, spec_path, client=client, budget=8,
                             proposals_root=tmp_path / "proposals", store="teststore")
    assert len(client.requests) == 1
    assert records[0]["status"] == "proposed"
    assert records[0]["response_id"] == "resp-1"
    assert "approval" not in records[0]
    saved = json.loads((tmp_path / "proposals" / "teststore" / "refund_over_limit.json").read_text(encoding="utf-8"))
    assert saved["status"] == "proposed"
    assert saved["policy_sha256"]
    assert extend.list_proposals(tmp_path / "proposals" / "teststore")