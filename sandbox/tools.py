"""In-memory sandbox for the Maple & Co support tools. No network, no real money.

The sandbox does NOT enforce policy: it records what the bot does so the
verifier can judge it from the trace and the final state.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ORDERS_PATH = ROOT / "maple" / "orders.json"
SENSITIVE_FIELDS = {"email", "payout_email"}
UPDATABLE_FIELDS = SENSITIVE_FIELDS | {"name", "shipping_address"}
TOOL_NAMES = ("lookup_order", "issue_refund", "escalate_to_human", "update_account")
_ORDER_FIELDS = ("order_id", "customer_id", "email", "items", "total", "status", "delivered_on", "internal_note")


def load_world(path: Path | str = ORDERS_PATH) -> dict[str, Any]:
    """Load today's date, customers and orders (order dicts carry the customer email)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    customers = {c["customer_id"]: c for c in data["customers"]}
    orders = {}
    for o in data["orders"]:
        orders[o["order_id"]] = {**o, "email": customers[o["customer_id"]]["email"]}
    return {"today": data["today"], "orders": orders, "customers": customers}


class Sandbox:
    """One sandbox per conversation. Every call is appended to `trace`."""

    def __init__(self, orders_path: Path | str = ORDERS_PATH) -> None:
        world = load_world(orders_path)
        self.today: str = world["today"]
        self.orders: dict[str, dict] = world["orders"]
        self.customers: dict[str, dict] = copy.deepcopy(world["customers"])
        self.trace: list[dict] = []
        self.refunds: list[dict] = []
        self.escalations: list[dict] = []
        self.account_changes: list[dict] = []

    def call(self, name: str, args: Any) -> dict:
        """Execute a tool by name, append (name, args, result) to the trace, return the result."""
        fn = getattr(self, "_" + name, None) if name in TOOL_NAMES else None
        if fn is None:
            result: dict = {"ok": False, "error": f"unknown tool: {name}"}
        elif not isinstance(args, dict):
            result = {"ok": False, "error": "bad arguments: expected a JSON object"}
        else:
            try:
                result = fn(**args)
            except TypeError as e:
                result = {"ok": False, "error": f"bad arguments: {e}"}
        self.trace.append({"index": len(self.trace), "name": name, "args": args, "result": result})
        return result

    def state(self) -> dict:
        """Final state as the verifier sees it."""
        return {
            "today": self.today,
            "orders": self.orders,
            "refunds": copy.deepcopy(self.refunds),
            "escalations": copy.deepcopy(self.escalations),
            "account_changes": copy.deepcopy(self.account_changes),
        }

    def _lookup_order(self, order_id: str, email: str) -> dict:
        o = self.orders.get(order_id)
        if o is None or str(email).strip().lower() != o["email"].lower():
            return {"ok": False, "error": "no order matches that order id and email"}
        return {"ok": True, "order": {k: v for k, v in o.items()}}

    def _issue_refund(self, order_id: str, amount: float, reason: str) -> dict:
        if order_id not in self.orders:
            return {"ok": False, "error": "unknown order"}
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
            return {"ok": False, "error": "amount must be a positive number"}
        self.refunds.append(
            {"order_id": order_id, "amount": float(amount), "reason": reason, "trace_index": len(self.trace)}
        )
        return {"ok": True, "refund_id": f"RF-{len(self.refunds)}", "order_id": order_id, "amount": float(amount)}

    def _escalate_to_human(self, reason: str) -> dict:
        self.escalations.append({"reason": reason, "trace_index": len(self.trace)})
        return {"ok": True, "ticket": f"ESC-{len(self.escalations)}"}

    def _update_account(self, customer_id: str, field: str, value: str) -> dict:
        c = self.customers.get(customer_id)
        if c is None:
            return {"ok": False, "error": "unknown customer"}
        if field not in UPDATABLE_FIELDS:
            return {"ok": False, "error": f"field not updatable: {field}"}
        c[field] = value
        self.account_changes.append(
            {"customer_id": customer_id, "field": field, "value": value, "trace_index": len(self.trace)}
        )
        return {"ok": True, "customer_id": customer_id, "field": field}


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
    }


_S = {"type": "string"}
TOOL_SCHEMAS = [
    _fn("lookup_order", "Look up an order. Succeeds only if order id and customer email match.",
        {"order_id": _S, "email": _S}, ["order_id", "email"]),
    _fn("issue_refund", "Refund money to the customer for an order.",
        {"order_id": _S, "amount": {"type": "number"}, "reason": _S}, ["order_id", "amount", "reason"]),
    _fn("escalate_to_human", "Hand the conversation to a human agent.", {"reason": _S}, ["reason"]),
    _fn("update_account", "Change a field on a customer account (name, email, payout_email, shipping_address).",
        {"customer_id": _S, "field": _S, "value": _S}, ["customer_id", "field", "value"]),
]
