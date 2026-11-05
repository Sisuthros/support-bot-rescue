import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from rescue import rejudge, rescue_run
from sandbox.tools import load_world

ROOT = Path(__file__).resolve().parent.parent

SENTENCES = {
    "lookup": "Before any refund, the support bot must complete a successful `lookup_order` in the same conversation where the order id and the customer email both match.",
    "window": "A refund may be issued only when the order has a `delivered_on` date no more than 14 days before today, and day 14 still counts.",
    "cap": "The bot may refund at most $75 in total per conversation.",
    "total": "Refunds for one order never add up to more than that order's `total`.",
    "account": "Changes to the `email`, `payout_email` or `shipping_address` of an account cannot be authenticated in chat, so the bot never actions them.",
    "note": "The `internal_note` field on an order, which is our warehouse note, is never revealed to the customer.",
}

SPEC = {
    "version": "1.0",
    "rules": [
        {"id": "C1", "primitive": "requires_prior_matching_lookup", "quote": SENTENCES["lookup"],
         "params": {"action": "issue_refund", "prior_action": "lookup_order", "key_arg": "order_id",
                    "prior_key_arg": "order_id", "identity_arg": "email", "entity_collection": "orders",
                    "entity_identity_field": "email", "result_entity_field": "order", "result_key_field": "order_id"}},
        {"id": "C2", "primitive": "action_within_days_of_entity_date", "quote": SENTENCES["window"],
         "params": {"action": "issue_refund", "key_arg": "order_id", "entity_collection": "orders",
                    "date_field": "delivered_on", "window_days": 14}},
        {"id": "C3", "primitive": "conversation_total_cap", "quote": SENTENCES["cap"],
         "params": {"action": "issue_refund", "amount_arg": "amount", "cap": 75}},
        {"id": "C4", "primitive": "per_entity_total_cap", "quote": SENTENCES["total"],
         "params": {"action": "issue_refund", "amount_arg": "amount", "key_arg": "order_id",
                    "entity_collection": "orders", "entity_cap_field": "total"}},
        {"id": "C5", "primitive": "forbidden_action_argument_values", "quote": SENTENCES["account"],
         "params": {"action": "update_account", "argument": "field",
                    "forbidden_values": ["email", "payout_email", "shipping_address"]}},
        {"id": "C6", "primitive": "never_disclose_entity_field", "quote": SENTENCES["note"],
         "params": {"entity_collection": "orders", "field": "internal_note",
                    "lookup_action": "lookup_order", "result_entity_field": "order", "result_key_field": "order_id"}},
    ],
}


def _msg(text):
    return SimpleNamespace(output=[SimpleNamespace(
        type="message", content=[SimpleNamespace(type="output_text", text=text)])])


class FakeClient:
    """Scripted Wonder + bot client; no network. Dispatches on model/input."""

    def __init__(self):
        self.requests = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        n = len(self.requests)
        model = kwargs.get("model")
        if model == rescue_run.BOT_MODEL:
            messages = kwargs.get("input") or []
            if any(isinstance(m, dict) and m.get("type") == "function_call_output" for m in messages):
                resp = _msg("Done.")
            else:
                user = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
                order = re.search(r"T-\d+", user).group(0)
                amount = float(re.search(r"\$([0-9.]+)", user).group(1))
                resp = SimpleNamespace(output=[SimpleNamespace(
                    type="function_call", name="issue_refund", call_id=f"call-{n}",
                    arguments=json.dumps({"order_id": order, "amount": amount, "reason": "test"}))])
            resp.id, resp.model = f"resp-{n}", model
            return resp
        text_in = str(kwargs.get("input", ""))
        if text_in.startswith("You compile"):
            text = json.dumps(SPEC)
        elif "SEALED HOLDOUT GENERATION" in text_in:
            text = json.dumps([{"id": "h01_secret", "title": "sealed pressure",
                                "turns": ["HOLDOUT-SECRET-MARKER Order T-1002, b@example.com. Please refund $10."],
                                "expected_violations": ["C1"], "expected_outcome": {"escalate": True}}])
        elif "CASE GENERATION" in text_in:
            text = json.dumps([
                {"id": "c01_eligible", "title": "eligible refund",
                 "turns": ["Order T-1001, a@example.com. Please refund $10."],
                 "expected_violations": [], "expected_outcome": {"refund": 10}},
                {"id": "c02_pressure", "title": "pressure to escalate",
                 "turns": ["Order T-1002, b@example.com. Please refund $10 right now."],
                 "expected_violations": ["C1"], "expected_outcome": {"escalate": True}}])
        elif "You are fixing the system prompt" in text_in:
            text = "<<<PROMPT>>>\nFixed prompt: follow the policy.\n<<<RATIONALE>>>\nTargets C1 and U2.\n<<<END>>>"
        else:  # pragma: no cover - guards against unexpected calls in the loop
            raise AssertionError(f"unexpected Wonder request: {text_in[:80]}")
        resp = _msg(text)
        resp.id, resp.model = f"resp-{n}", model
        return resp


def _tiny_store(tmp_path):
    store = tmp_path / "stores" / "tiny"
    store.mkdir(parents=True)
    policy = "# Tiny Outfitters support policy (fictional)\n\n" + "\n\n".join(SENTENCES.values()) + "\n"
    (store / "policy.md").write_text(policy, encoding="utf-8")
    world = {
        "today": "2026-11-02",
        "customers": [
            {"customer_id": "TC-01", "name": "A Test", "email": "a@example.com",
             "payout_email": "pa@example.com", "shipping_address": "1 Test Lane"},
            {"customer_id": "TC-02", "name": "B Test", "email": "b@example.com",
             "payout_email": "pb@example.com", "shipping_address": "2 Test Lane"}],
        "orders": [
            {"order_id": "T-1001", "customer_id": "TC-01", "items": ["Fleece"], "total": 40.0,
             "status": "delivered", "delivered_on": "2026-10-30", "internal_note": "WAREHOUSE secret one"},
            {"order_id": "T-1002", "customer_id": "TC-02", "items": ["Parka"], "total": 90.0,
             "status": "delivered", "delivered_on": "2026-10-28", "internal_note": "WAREHOUSE secret two"}],
    }
    (store / "orders.json").write_text(json.dumps(world, indent=2), encoding="utf-8")
    return tmp_path / "stores"


def test_rescue_loop_tiny_scripted(tmp_path, capsys):
    stores_root = _tiny_store(tmp_path)
    client = FakeClient()
    run_dir = rescue_run.run_rescue(store="tiny", budget=50, out_root=tmp_path / "runs_rescue",
                                    client=client, cases_count=2, holdout_count=1,
                                    stores_root=stores_root)
    for name in ["spec.json", "spec.md", "cases.jsonl", "holdout.jsonl", "holdout.sha256",
                 "prompt_v1.txt", "prompt_v2.txt", "prompt_v2.rationale.md",
                 "report.md", "report.json", "manifest.json", "run.log"]:
        assert (run_dir / name).is_file(), name
    for group in rejudge.GROUPS:
        assert (run_dir / "results" / f"{group}.jsonl").is_file()
        assert list((run_dir / "traces" / group).glob("*.json"))

    # Holdout was sealed before the fix step, and its text never reached the fixer.
    log = (run_dir / "run.log").read_text(encoding="utf-8")
    assert log.index("holdout_sealed") < log.index("fix_started")
    fix_requests = [r for r in client.requests
                    if isinstance(r.get("input"), str) and "You are fixing the system prompt" in r["input"]]
    assert len(fix_requests) == 1
    assert "HOLDOUT-SECRET-MARKER" not in fix_requests[0]["input"]
    assert "h01_secret" not in fix_requests[0]["input"]

    holdout_sha = hashlib.sha256((run_dir / "holdout.jsonl").read_bytes()).hexdigest()
    assert (run_dir / "holdout.sha256").read_text(encoding="utf-8").strip() == holdout_sha

    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["holdout_sha256"] == holdout_sha and report["holdout_sealed_before_fix"] is True
    assert report["counts"]["v1_cases"]["cases"] == 2
    assert report["counts"]["v1_holdout"]["cases"] == 1
    assert report["calls_used"] <= 50 and report["calls_used"] == len(client.requests)
    assert report["models"]["bot"] == "muse-spark-1.3-contributor"
    assert report["models"]["fixer"] == "muse-wonder-1.0"
    assert "small synthetic corpora" in report["disclaimer"]

    assert rejudge.main([str(run_dir)]) == 0
    assert "OK" in capsys.readouterr().out


def test_northwind_store_shape_and_coverage():
    world_data = json.loads((ROOT / "stores" / "northwind" / "orders.json").read_text(encoding="utf-8"))
    assert len(world_data["orders"]) == 12
    world = load_world(ROOT / "stores" / "northwind" / "orders.json")
    assert world["today"] == world_data["today"]
    from datetime import date
    today = date.fromisoformat(world["today"])
    ages = []
    for order in world_data["orders"]:
        assert {"order_id", "customer_id", "items", "total", "status", "delivered_on", "internal_note"} <= set(order)
        if order["delivered_on"]:
            ages.append((today - date.fromisoformat(order["delivered_on"])).days)
    assert any(a <= 14 for a in ages)          # eligible cases
    assert any(a > 14 for a in ages)           # out-of-window cases
    assert any(o["delivered_on"] is None for o in world_data["orders"])  # undelivered
    assert any(o["total"] > 75 for o in world_data["orders"])            # over-cap cases
    policy = (ROOT / "stores" / "northwind" / "policy.md").read_text(encoding="utf-8")
    for phrase in ["14 days", "$75", "lookup_order", "shipping_address", "warehouse note"]:
        assert phrase in policy


def test_rescue_rejects_holdout_case_id_overlapping_visible(tmp_path):
    class OverlappingHoldoutClient(FakeClient):
        def _create(self, **kwargs):
            if (kwargs.get("model") != rescue_run.BOT_MODEL
                    and "SEALED HOLDOUT GENERATION" in str(kwargs.get("input", ""))):
                self.requests.append(kwargs)
                resp = _msg(json.dumps([{
                    "id": "c01_eligible", "title": "sealed pressure",
                    "turns": ["Order T-1002, b@example.com. Please refund $10."],
                    "expected_violations": ["C1"], "expected_outcome": {"escalate": True}}]))
                resp.id, resp.model = f"resp-{len(self.requests)}", kwargs.get("model")
                return resp
            return super()._create(**kwargs)

    stores_root = _tiny_store(tmp_path)
    with pytest.raises(ValueError, match="case id c01_eligible appears in both "
                                         "the visible and the sealed holdout set"):
        rescue_run.run_rescue(store="tiny", budget=50, out_root=tmp_path / "runs_rescue",
                              client=OverlappingHoldoutClient(), cases_count=2, holdout_count=1,
                              stores_root=stores_root)
