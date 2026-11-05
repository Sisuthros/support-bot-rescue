"""Replay reconstructed incidents through the scored judge.

Run as ``py -3 -m incidents.replay``. Each stored trace is executed on a
fresh ``sandbox.tools.Sandbox`` (the Maple sandbox world) and judged with
``verifier.rules.check_all`` -- the same judge function the scored runs use
(see ``run.py``). This module adds no rule logic of its own. After the rule
verdict, ``incidents.text_claims.check_reply`` flags free-text policy
claims that the Maple policy text does not ground. A flag is a review
prompt only; it is not a rule violation.
"""
from __future__ import annotations

import sys
from pathlib import Path

from incidents.scenarios import SCENARIOS
from incidents.text_claims import check_reply
from sandbox.tools import Sandbox
from verifier.rules import check_all

_FAILURE_KINDS = {"bad"}
POLICY_PATH = Path(__file__).resolve().parent.parent / "maple" / "policy.md"


def _policy_text() -> str:
    """Return the Maple policy text used by the sandbox and the judge."""
    return POLICY_PATH.read_text(encoding="utf-8")


def judge_trace(trace_spec: dict) -> list[dict]:
    """Execute one stored trace on the sandbox and return judge violations."""
    sandbox = Sandbox()
    for call in trace_spec["tool_calls"]:
        sandbox.call(call["name"], call["args"])
    return check_all(sandbox.trace, sandbox.state(), trace_spec["reply"])


def actual_verdict(trace_spec: dict, violations: list[dict]) -> str:
    if violations:
        rules = ",".join(sorted({v["rule"] for v in violations}))
        return f"caught:{rules}"
    if trace_spec["kind"] in _FAILURE_KINDS:
        return "not_caught"
    return "no_violation"


def evaluate(scenarios=SCENARIOS) -> list[dict]:
    """Judge every trace; return one result dict per trace."""
    policy_text = _policy_text()
    results = []
    for scenario in scenarios:
        for trace_spec in scenario["traces"]:
            violations = judge_trace(trace_spec)
            actual = actual_verdict(trace_spec, violations)
            flags = check_reply(trace_spec["reply"], policy_text)
            actual_flag = flags[0]["flag"] if flags else None
            expected_flag = trace_spec["expected_flag"]
            results.append(
                {
                    "scenario": scenario,
                    "trace": trace_spec,
                    "violations": violations,
                    "actual": actual,
                    "expected": trace_spec["expected_verdict"],
                    "flags": flags,
                    "actual_flag": actual_flag,
                    "expected_flag": expected_flag,
                    "match": actual == trace_spec["expected_verdict"]
                    and actual_flag == expected_flag,
                }
            )
    return results


def _rule_label(result: dict) -> str:
    rule_ids = result["scenario"]["rule_ids"]
    return ",".join(rule_ids) if rule_ids else "-"


def _flag_label(result: dict) -> str:
    if result["actual_flag"] == "ungrounded_policy_claim":
        return "flagged: ungrounded policy claim"
    return "flagged: none"


def main() -> int:
    results = evaluate()
    for result in results:
        scenario = result["scenario"]
        status = "MATCH" if result["match"] else "MISMATCH"
        verdict = result["actual"]
        if verdict == "not_caught":
            verdict = "not_caught by rules"
        print(
            f"{scenario['id']}/{result['trace']['id']} | {scenario['source']} | "
            f"{_rule_label(result)} | {result['expected']} | {verdict} | "
            f"{_flag_label(result)} | {status}"
        )
    failures = [r for r in results if r["trace"]["kind"] in _FAILURE_KINDS]
    caught = [r for r in failures if r["actual"].startswith("caught:")]
    not_caught = [r for r in failures if r["actual"] == "not_caught"]
    flagged = [r for r in results if r["actual_flag"] is not None]
    print(f"coverage: caught {len(caught)} of {len(failures)} failure modes")
    print(f"flagged: {len(flagged)} of {len(results)} traces")
    for result in not_caught:
        print(
            f"not_caught: {result['scenario']['id']}/{result['trace']['id']} - "
            f"{result['trace']['reason']}"
        )
    return 0 if all(r["match"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
