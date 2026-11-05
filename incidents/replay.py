"""Replay reconstructed incidents through the scored judge.

Run as ``py -3 -m incidents.replay``. Each stored trace is executed on a
fresh ``sandbox.tools.Sandbox`` (the Maple sandbox world) and judged with
``verifier.rules.check_all`` -- the same judge function the scored runs use
(see ``run.py``). This module adds no rule logic of its own.
"""
from __future__ import annotations

import sys

from incidents.scenarios import SCENARIOS
from sandbox.tools import Sandbox
from verifier.rules import check_all

_FAILURE_KINDS = {"bad"}


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
    results = []
    for scenario in scenarios:
        for trace_spec in scenario["traces"]:
            violations = judge_trace(trace_spec)
            actual = actual_verdict(trace_spec, violations)
            results.append(
                {
                    "scenario": scenario,
                    "trace": trace_spec,
                    "violations": violations,
                    "actual": actual,
                    "expected": trace_spec["expected_verdict"],
                    "match": actual == trace_spec["expected_verdict"],
                }
            )
    return results


def _rule_label(result: dict) -> str:
    rule_ids = result["scenario"]["rule_ids"]
    return ",".join(rule_ids) if rule_ids else "-"


def main() -> int:
    results = evaluate()
    for result in results:
        scenario = result["scenario"]
        status = "MATCH" if result["match"] else "MISMATCH"
        print(
            f"{scenario['id']}/{result['trace']['id']} | {scenario['source']} | "
            f"{_rule_label(result)} | {result['expected']} | {result['actual']} | {status}"
        )
    failures = [r for r in results if r["trace"]["kind"] in _FAILURE_KINDS]
    caught = [r for r in failures if r["actual"].startswith("caught:")]
    not_caught = [r for r in failures if r["actual"] == "not_caught"]
    print(f"coverage: caught {len(caught)} of {len(failures)} failure modes")
    for result in not_caught:
        print(
            f"not_caught: {result['scenario']['id']}/{result['trace']['id']} - "
            f"{result['trace']['reason']}"
        )
    return 0 if all(r["match"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
