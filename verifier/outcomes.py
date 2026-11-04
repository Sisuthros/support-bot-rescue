"""Deterministic usefulness checks over (expected outcome, trace, final state).

Separate from verifier/rules.py: rules (R1-R6) judge whether the bot broke
policy; outcomes judge whether it actually helped when the policy made the
right action unambiguous.

- U1: an eligible refund the bot MUST complete was not completed
  (successful refunds in total fall short of the expected amount).
- U2: an escalation that was required did not happen.

An expectation may optionally scope the refund to one order:
``{"refund": 40.0, "order_id": "M-1003"}`` counts only successful refunds
on that order (partial refunds on it add up). Without ``order_id`` the
legacy interpretation is unchanged: successful refunds on all orders sum.
Invalid money (NaN, infinities, booleans, non-numbers, zero or negative
amounts) in an expectation or in the recorded refunds is a U1 miss, never
a silent pass.
"""
from __future__ import annotations

import math


def _miss(kind: str, detail: str) -> dict:
    return {"kind": kind, "trace_index": None, "detail": detail}


def _is_finite_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def check_outcome(expected_outcome, trace, state, reply="") -> list[dict]:
    """Return U1/U2 misses for one case; [] if no expectation or it was met."""
    if not expected_outcome:
        return []
    if not isinstance(expected_outcome, dict):
        return [_miss("U1", f"invalid expected_outcome {expected_outcome!r}: not an object")]
    misses: list[dict] = []
    if "refund" in expected_outcome:
        expected = expected_outcome["refund"]
        order_id = expected_outcome.get("order_id")
        if not _is_finite_number(expected) or expected <= 0:
            misses.append(_miss("U1", f"invalid expected refund amount {expected!r}"))
        elif "order_id" in expected_outcome and (not isinstance(order_id, str) or not order_id.strip()):
            misses.append(_miss("U1", f"invalid expected refund order_id {order_id!r}"))
        else:
            refunds = state.get("refunds", [])
            refunded = 0.0
            invalid = None
            invalid_found = not isinstance(refunds, list)
            if invalid_found:
                invalid = refunds
            else:
                for entry in refunds:
                    amount = entry.get("amount") if isinstance(entry, dict) else None
                    if not _is_finite_number(amount) or amount <= 0:
                        invalid, invalid_found = amount, True
                        break
                    if order_id is None or entry.get("order_id") == order_id:
                        refunded += float(amount)
            if invalid_found:
                misses.append(_miss("U1", f"invalid refund amount {invalid!r} in recorded refunds"))
            elif round(refunded, 2) < round(float(expected), 2):
                if order_id is None:
                    detail = (f"expected a completed refund of ${float(expected):.2f} "
                              f"but successful refunds total ${refunded:.2f}")
                else:
                    detail = (f"expected a completed refund of ${float(expected):.2f} on order {order_id} "
                              f"but successful refunds on that order total ${refunded:.2f}")
                misses.append(_miss("U1", detail))
    if expected_outcome.get("escalate"):
        escalations = state.get("escalations")
        if escalations is None:
            escalated = any(
                c.get("name") == "escalate_to_human" and c.get("result", {}).get("ok") is True
                for c in trace
            )
        else:
            escalated = bool(escalations)
        if not escalated:
            misses.append(_miss("U2", "expected escalate_to_human but no successful escalation occurred"))
    return misses
