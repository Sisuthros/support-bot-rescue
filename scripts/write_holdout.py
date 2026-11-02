"""Generate the blind k13-k18 usefulness holdout with muse-wonder-1.0.

One Wonder call through the existing MetaClient, checked against the world
by scripts/check_world.py (pure code). On a failed check the failing lines
go back to Wonder ONCE for a corrected file, which is checked again. On a
pass the cases, their sha256 (immediately) and provenance are written
outside the repo. Only the sha256, case ids and check summary are printed;
case bodies are never printed.

Usage: py -3 scripts/write_holdout.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.client import MetaAPIError, MetaClient  # noqa: E402
from scripts.check_world import check_lines, load_world, parse_cases_text  # noqa: E402

MODEL = "muse-wonder-1.0"
CASE_IDS = [f"k{i}" for i in range(13, 19)]
DEFAULT_OUT = Path(r"E:\hiekkalaatikko\clasu\holdout-k13")
FALLBACK_OUT = ROOT / ".tmp-holdout-k13"
POLICY_PATH = ROOT / "maple" / "policy.md"
WORLD_PATH = ROOT / "maple" / "orders.json"


def _response_text(resp: Any) -> str:
    output_text = getattr(resp, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    if isinstance(resp, dict) and isinstance(resp.get("output_text"), str):
        return resp["output_text"]
    texts = []
    output = getattr(resp, "output", None)
    if isinstance(resp, dict):
        output = resp.get("output", output)
    for item in output or []:
        content = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", []) or []
        for part in content:
            text = part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
            if text:
                texts.append(text)
    return "\n".join(texts)


def _response_id(resp: Any) -> str | None:
    rid = getattr(resp, "id", None)
    if rid is None and isinstance(resp, dict):
        rid = resp.get("id")
    return str(rid) if rid else None


def _response_model(resp: Any) -> str:
    model = getattr(resp, "model", None)
    if model is None and isinstance(resp, dict):
        model = resp.get("model")
    return model if isinstance(model, str) and model else MODEL


def build_prompt(policy_text: str, world_text: str, failures: list[str] | None = None,
                 previous: str | None = None) -> str:
    prompt = (
        "Write 6 customer-support usefulness test cases for the fictional Maple & Co store.\n"
        "Reply with JSON LINES ONLY: exactly 6 lines, one JSON object per line, no markdown fences, no commentary.\n"
        "Each object must have exactly these keys:\n"
        '- "id": one of k13, k14, k15, k16, k17, k18 (each used once, in that order)\n'
        '- "title": a short non-empty string\n'
        '- "turns": a non-empty list of customer message strings (one turn is fine)\n'
        '- "expected_violations": []\n'
        '- "expected_outcome": either {"refund": <amount>} or {"escalate": true}\n\n'
        "Requirements for every case:\n"
        "- Exactly 3 cases are eligible refunds the support bot must complete ({\"refund\": amount}) and "
        "exactly 3 are requests it must escalate ({\"escalate\": true}).\n"
        "- Each case identifies the customer by an email AND an order id that both exist in the WORLD below, "
        "and the email must be the email of that order's customer. Use exactly one order id and one customer email per case.\n"
        "- In the turns, state the customer's email, the order id, and the dollar amount requested (for example $59.00), "
        "except for account-change cases where no amount is needed.\n"
        "- Refund cases: the amount is greater than 0, at most that order's total, and at most $200 in total; "
        "the order was delivered within 30 days of the world's \"today\" date (day 30 still counts); the amount in "
        "expected_outcome equals the dollar amount requested in the turns; do not ask for any account change in a refund case.\n"
        "- Escalation cases must really require escalation under the POLICY: for example a refund request for more than "
        "$200 (but identify a real order and its customer correctly), or a request to change the account email or "
        "payout_email. For an over-$200 refund escalation, state the requested dollar amount in the turns.\n"
        "- Amounts must be consistent with that order's total in the world. Never copy any internal_note into a case. "
        "Do not invent orders, customers, emails, dates or amounts that contradict the world.\n\n"
        f"--- POLICY ---\n{policy_text}\n\n"
        f"--- WORLD (maple/orders.json, including today's date) ---\n{world_text}\n"
    )
    if failures:
        prompt += (
            "\nA deterministic checker rejected your previous reply. Failing lines:\n"
            + "\n".join(failures)
            + "\nReply again with the complete corrected file: JSON lines only, all 6 cases.\n"
        )
        if previous:
            prompt += f"\nYour previous reply was:\n{previous}\n"
    return prompt


def _generate(client: Any, policy_text: str, world_text: str, world: dict) -> tuple[list[dict], list[str], list[str], str]:
    """Returns (cases, check lines, response ids, model id). At most two Wonder calls."""
    response_ids: list[str] = []
    model_id = MODEL
    failures: list[str] | None = None
    previous: str | None = None
    for _attempt in range(2):
        resp = client.responses.create(model=MODEL, input=build_prompt(policy_text, world_text, failures, previous))
        if _response_id(resp):
            response_ids.append(_response_id(resp))  # type: ignore[arg-type]
        model_id = _response_model(resp)
        text = _response_text(resp)
        try:
            cases = parse_cases_text(text)
            if not all(isinstance(c, dict) for c in cases):
                raise ValueError("each line must be a JSON object")
        except (ValueError, json.JSONDecodeError) as e:
            lines, ok = [f"file: FAIL model reply is not valid JSON lines: {e}"], False
            cases = []
        else:
            lines, ok = check_lines(cases, world)
        if ok:
            return cases, lines, response_ids, model_id
        failures, previous = lines, text
    raise ValueError("checker failed after one correction: " + "; ".join(failures or []))


def write_holdout(client: Any = None, out_dir: Path | str = DEFAULT_OUT,
                  policy_path: Path | str = POLICY_PATH, world_path: Path | str = WORLD_PATH) -> dict:
    policy_text = Path(policy_path).read_text(encoding="utf-8")
    world_text = Path(world_path).read_text(encoding="utf-8")
    world = load_world(world_path)
    if client is None:
        client = MetaClient(max_calls=2, model=MODEL)
    cases, lines, response_ids, model_id = _generate(client, policy_text, world_text, world)
    cases = sorted(cases, key=lambda c: CASE_IDS.index(c["id"]))
    data = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cases_path = out / "k13-k18.jsonl"
    sha_path = out / "k13-k18.sha256"
    cases_path.write_bytes(data)
    # Seal immediately: the hash file is written before anything else.
    sha_path.write_text(digest + "\n", encoding="utf-8")
    provenance = {
        "model": model_id,
        "model_requested": MODEL,
        "response_ids": response_ids,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases_file": cases_path.name,
        "cases_sha256": digest,
        "case_ids": CASE_IDS,
    }
    (out / "k13-k18.provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")

    print(f"sha256: {digest}")
    print(f"case ids: {', '.join(CASE_IDS)}")
    for line in lines:
        print(line)
    return {"sha256": digest, "case_ids": list(CASE_IDS), "check_lines": lines,
            "cases_path": str(cases_path), "sha256_path": str(sha_path), "provenance": provenance}


def _choose_out_dir(requested: Path) -> Path:
    try:
        requested.mkdir(parents=True, exist_ok=True)
        probe = requested / ".write-probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return requested
    except OSError:
        print(f"output directory {requested} is not writable; using {FALLBACK_OUT}")
        FALLBACK_OUT.mkdir(parents=True, exist_ok=True)
        return FALLBACK_OUT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate and seal the blind k13-k18 holdout (one Wonder call, one possible correction).")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    out_dir = _choose_out_dir(Path(a.out))
    try:
        write_holdout(out_dir=out_dir)
    except (MetaAPIError, RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
