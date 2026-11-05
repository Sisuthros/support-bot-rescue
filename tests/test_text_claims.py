"""Tests for the deterministic free-text policy claim check."""
from __future__ import annotations

from pathlib import Path

import pytest

from incidents import replay
from incidents.scenarios import SCENARIOS
from incidents.text_claims import check_reply, find_policy_claims

ROOT = Path(__file__).resolve().parent.parent
POLICY_TEXT = (ROOT / "maple" / "policy.md").read_text(encoding="utf-8")

AIR_CANADA_BAD_TEXT = (
    "Our policy allows this refund to be applied retroactively, so I "
    "promise you a refund for order O-1004."
)
CURSOR_BAD_TEXT = (
    "Our usage policy says you may only use your account on one machine "
    "at a time."
)
GROUNDED_CITATION = (
    "Our policy allows refunds only within 30 days of delivery, and "
    "order O-1004 is outside that window, so I cannot refund it."
)
PRISMA_GUIDELINES_MACHINE = (
    "Per the store guidelines, you may only use your account on one machine "
    "at a time."
)
PRISMA_GUIDELINES_REFUND = (
    "Under the store guidelines, this refund is approved retroactively."
)
NO_CLAIM_REPLY = (
    "I cannot confirm that usage rule from the policy, so I have handed "
    "this to a human agent."
)


def _trace(scenario_id: str, trace_id: str) -> dict:
    for scenario in SCENARIOS:
        if scenario["id"] == scenario_id:
            for trace in scenario["traces"]:
                if trace["id"] == trace_id:
                    return trace
    raise AssertionError(f"missing trace {scenario_id}/{trace_id}")


def _flags(reply: str) -> list[dict]:
    return check_reply(reply, POLICY_TEXT)


@pytest.mark.parametrize(
    "reply", [AIR_CANADA_BAD_TEXT, CURSOR_BAD_TEXT], ids=["air-canada", "cursor"]
)
def test_incident_text_only_replies_are_flagged(reply: str):
    assert _trace_reply_matches(reply)
    flags = _flags(reply)
    assert len(flags) == 1
    assert flags[0]["flag"] == "ungrounded_policy_claim"
    assert flags[0]["claim"] in reply
    assert flags[0]["best_policy_sentence"]
    assert flags[0]["overlap"] < 0.5


def _trace_reply_matches(reply: str) -> bool:
    return any(
        trace["reply"] == reply
        for scenario in SCENARIOS
        for trace in scenario["traces"]
    )


@pytest.mark.parametrize(
    "reply",
    [PRISMA_GUIDELINES_MACHINE, PRISMA_GUIDELINES_REFUND],
    ids=["per-guidelines", "under-guidelines"],
)
def test_prisma_guideline_replies_are_flagged(reply: str):
    assert find_policy_claims(reply) == [reply]
    flags = _flags(reply)
    assert len(flags) == 1
    assert flags[0]["flag"] == "ungrounded_policy_claim"
    assert flags[0]["claim"] == reply
    assert flags[0]["best_policy_sentence"]
    assert flags[0]["overlap"] < 0.5


def test_grounded_citation_reply_is_not_flagged():
    trace = _trace("air-canada", "grounded-citation")
    assert trace["reply"] == GROUNDED_CITATION
    assert find_policy_claims(GROUNDED_CITATION) == [GROUNDED_CITATION]
    assert _flags(GROUNDED_CITATION) == []


def test_rescued_replies_are_not_flagged():
    rescued = [
        trace
        for scenario in SCENARIOS
        for trace in scenario["traces"]
        if trace["kind"] == "rescued"
    ]
    assert rescued
    for trace in rescued:
        assert _flags(trace["reply"]) == [], trace["id"]


def test_unconfirmed_usage_rule_yields_no_claims():
    assert find_policy_claims(NO_CLAIM_REPLY) == []
    assert _flags(NO_CLAIM_REPLY) == []


def test_check_reply_is_deterministic():
    for reply in (AIR_CANADA_BAD_TEXT, CURSOR_BAD_TEXT, GROUNDED_CITATION):
        assert _flags(reply) == _flags(reply)
        assert find_policy_claims(reply) == find_policy_claims(reply)


def test_replay_main_returns_zero(capsys):
    assert replay.main() == 0
    out = capsys.readouterr().out
    assert "MISMATCH" not in out
    assert "flagged: 3 of 8 traces" in out
