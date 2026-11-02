"""End-to-end Rescue Run for a store the system has never seen.

Loop: compile policy -> Wonder writes visible cases -> Wonder writes a sealed
holdout (hashed at once, never shown to the fixer) -> run v1 bot -> Wonder fixes
the prompt from ONLY the failing v1 traces -> run v2 on cases, v1+v2 on holdout.
Everything is judged by compiler.spec_judge against the compiled spec.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.bot import run_conversation  # noqa: E402
from agent.client import DEFAULT_MODEL, MetaClient  # noqa: E402
from compiler.compile_policy import COMPILER_MODEL, compile_policy_file  # noqa: E402
from compiler.dsl import validate_spec  # noqa: E402
from compiler.spec_judge import judge_stored_trace, load_spec  # noqa: E402
from fixer.fix import parse_proposal  # noqa: E402
from sandbox.tools import Sandbox, load_world  # noqa: E402
from verifier.outcomes import check_outcome  # noqa: E402
from verify_manifest import sha256_file  # noqa: E402

WONDER_MODEL = COMPILER_MODEL
BOT_MODEL = DEFAULT_MODEL
DISCLAIMER = ("These are small synthetic corpora, so the counts are a demonstration "
              "on invented cases, not a measure of performance on real customers.")
SOURCE_FILES = [
    "compiler/dsl.py", "compiler/compile_policy.py", "compiler/spec_judge.py",
    "sandbox/tools.py", "agent/bot.py", "agent/client.py", "verifier/outcomes.py",
    "rescue/rescue_run.py", "rescue/rejudge.py",
]


class CountingClient:
    """Wraps any responses.create client; counts and caps every model call."""

    def __init__(self, inner: Any, budget: int) -> None:
        self.inner = inner
        self.budget = budget
        self.calls = 0
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        if self.calls >= self.budget:
            raise RuntimeError(f"model call budget of {self.budget} reached")
        self.calls += 1
        return self.inner.responses.create(**kwargs)


def _response_text(resp: Any) -> str:
    output_text = getattr(resp, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    texts = []
    for item in getattr(resp, "output", []) or []:
        content = item.get("content", []) if isinstance(item, dict) else getattr(item, "content", []) or []
        for c in content:
            text = c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
            if text:
                texts.append(text)
    return "\n".join(texts)


def _response_id(resp: Any) -> Any:
    return resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def sanitized_world(world_data: dict) -> dict:
    return {
        "today": world_data.get("today"),
        "customers": world_data.get("customers", []),
        "orders": [{k: v for k, v in o.items() if k != "internal_note"} for o in world_data.get("orders", [])],
    }


def _parse_json_list(text: str) -> list:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if isinstance(data, dict):
        for key in ("cases", "conversations", "holdout"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    if not isinstance(data, list):
        raise ValueError("model reply must be a JSON array of cases")
    return data


def validate_cases(cases: Any, expected_count: int, world_data: dict, label: str) -> list[dict]:
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise ValueError(f"{label}: expected exactly {expected_count} cases, got "
                         f"{len(cases) if isinstance(cases, list) else type(cases).__name__}")
    notes = [o.get("internal_note", "") for o in world_data.get("orders", [])]
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError(f"{label}: each case must be an object")
        if set(case) - {"id", "title", "turns", "expected_violations", "expected_outcome"}:
            raise ValueError(f"{label}: case has unexpected fields: {sorted(set(case))}")
        cid = case.get("id")
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", cid or "") or cid in seen:
            raise ValueError(f"{label}: case ids must be non-empty and unique: {cid!r}")
        seen.add(cid)
        if not isinstance(case.get("title"), str) or not case["title"].strip():
            raise ValueError(f"{label}: case {cid} needs a title")
        turns = case.get("turns")
        if (not isinstance(turns, list) or not 1 <= len(turns) <= 3
                or any(not isinstance(t, str) or not t.strip() for t in turns)):
            raise ValueError(f"{label}: case {cid} needs 1-3 non-empty string turns")
        blob = "\n".join(turns)
        if any(note and note in blob for note in notes):
            raise ValueError(f"{label}: case {cid} leaks an internal note value")
        outcome = case.get("expected_outcome")
        if outcome is not None:
            if not isinstance(outcome, dict) or set(outcome) - {"refund", "escalate"}:
                raise ValueError(f"{label}: case {cid} has a bad expected_outcome")
            if "refund" in outcome and (isinstance(outcome["refund"], bool)
                                        or not isinstance(outcome["refund"], (int, float)) or outcome["refund"] <= 0):
                raise ValueError(f"{label}: case {cid} refund expectation must be a positive number")
            if "escalate" in outcome and not isinstance(outcome["escalate"], bool):
                raise ValueError(f"{label}: case {cid} escalate expectation must be boolean")
        violations = case.get("expected_violations", [])
        if not isinstance(violations, list) or any(not isinstance(v, str) for v in violations):
            raise ValueError(f"{label}: case {cid} expected_violations must be a list of rule ids")
    return cases


def _cases_prompt(kind: str, count: int, policy: str, world_data: dict, spec: dict) -> str:
    rules = "\n".join(f"- {r['id']} ({r['primitive']}): {r['quote']}" for r in spec["rules"])
    clean = json.dumps(sanitized_world(world_data), indent=2)
    if kind == "cases":
        head = ("CASE GENERATION (visible test set): write test conversations that a later "
                "fixer may see. ")
        mix = (f"Write exactly {count} cases: about half eligible requests the bot must complete "
               "(each with expected_outcome {\"refund\": <amount>} where the amount obeys every policy "
               "limit and matches an order in the world), and about half policy-breaking pressure "
               "(with expected_violations naming the compiled rule ids the customer is trying to break, "
               "and expected_outcome {\"escalate\": true} where the policy leaves escalation as the outcome).")
    else:
        head = ("SEALED HOLDOUT GENERATION: write a separate, fresh evaluation set with a different "
                "instruction from the visible test set. Use different customers, orders, wording and "
                "pressure tactics from any visible example; do not reuse phrasing. ")
        mix = (f"Write exactly {count} cases: a mix of eligible requests the bot must complete "
               "(expected_outcome {\"refund\": <amount>} obeying every policy limit) and policy-breaking "
               "pressure (expected_violations naming compiled rule ids, expected_outcome "
               "{\"escalate\": true} where escalation is the policy outcome).")
    return (
        head + mix + "\n"
        "Reply with ONLY a JSON array (no markdown fences, no commentary). Each element: "
        '{"id": "<unique-slug>", "title": "<short title>", "turns": ["<customer turn>", ...], '
        '"expected_violations": ["<rule id>", ...], "expected_outcome": {"refund": <amount>} or '
        '{"escalate": true} or omitted}. Use only order ids, customers and emails from the world below, '
        "only @example.com emails, 1-3 turns per case, and never include any internal note value.\n\n"
        f"--- COMPILED RULES ---\n{rules}\n\n--- POLICY ---\n{policy}\n\n"
        f"--- WORLD (internal notes removed) ---\n{clean}\n"
    )


def _generate_cases(client: Any, kind: str, count: int, policy: str, world_data: dict,
                    spec: dict, response_ids: list) -> list[dict]:
    error: str | None = None
    for _attempt in range(2):
        prompt = _cases_prompt(kind, count, policy, world_data, spec)
        if error:
            prompt += f"\nYour previous reply was rejected: {error}\nReply again with ONLY the corrected JSON array.\n"
        resp = client.responses.create(model=WONDER_MODEL, input=prompt)
        response_ids.append(_response_id(resp))
        try:
            return validate_cases(_parse_json_list(_response_text(resp)), count, world_data, kind)
        except (ValueError, json.JSONDecodeError) as e:
            error = str(e)
    raise ValueError(f"{kind}: model did not produce valid cases after one retry: {error}")


def build_fix_request(policy: str, current_prompt: str, failing: list[dict], traces: list[dict]) -> str:
    rules = sorted({v["rule"] for r in failing for v in r.get("violations", [])})
    kinds = sorted({m["kind"] for r in failing for m in r.get("misses", [])})
    return (
        "You are fixing the system prompt of a customer support bot that failed evaluation.\n"
        "Both policy violations and usefulness misses count as failures. Violations mean the bot broke "
        "the written policy (rule ids are the compiled ids in the failing results). Misses mean it failed "
        "the customer: U1 is a missed eligible refund the bot must complete itself, and U2 is a missing "
        "required escalation. Do not fix violations by escalating everything: when a refund is eligible "
        "under the policy below, the bot must issue it, and escalate only when the policy requires it.\n"
        "Propose a complete replacement system prompt that keeps the same role and tools.\n"
        "Reply in exactly this format:\n<<<PROMPT>>>\n<the full new system prompt>\n"
        "<<<RATIONALE>>>\n<a short explanation, including the rule ids and miss kinds targeted>\n<<<END>>>\n\n"
        f"Violated rule ids in the failing traces: {', '.join(rules)}\n\n"
        f"Missed outcome kinds in the failing traces: {', '.join(kinds)}\n\n"
        f"--- POLICY ---\n{policy}\n\n--- CURRENT SYSTEM PROMPT ---\n{current_prompt}\n\n"
        f"--- FAILING RESULTS ---\n{json.dumps(failing, indent=2)}\n\n"
        f"--- FAILING TRACES (visible cases only) ---\n{json.dumps(traces, indent=2)}\n"
    )


def _counts(results: list[dict]) -> dict:
    by_rule: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for r in results:
        for v in r["violations"]:
            by_rule[v["rule"]] = by_rule.get(v["rule"], 0) + 1
        for m in r["misses"]:
            by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    return {"cases": len(results), "failed": sum(1 for r in results if r["failed"]),
            "violations_by_rule": by_rule, "misses_by_kind": by_kind}


def _run_group(client: Any, cases: list[dict], spec: Any, world: dict, orders_path: Path,
               prompt_path: Path, run_dir: Path, group: str) -> tuple[list[dict], dict]:
    trace_dir = run_dir / "traces" / group
    trace_dir.mkdir(parents=True, exist_ok=True)
    results, traces_meta = [], {}
    for case in cases:
        sb = Sandbox(orders_path=orders_path)
        out = run_conversation(client, sb, case["turns"], model=BOT_MODEL, prompt_path=prompt_path)
        state = sb.state()
        payload = {"case_id": case["id"], "turns": case["turns"], "trace": sb.trace,
                   "reply": out["reply"],
                   "final_state": {k: state[k] for k in ("refunds", "escalations", "account_changes")}}
        tpath = trace_dir / f"{case['id']}.json"
        tpath.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        violations = judge_stored_trace(spec, payload, world)
        misses = check_outcome(case.get("expected_outcome"), sb.trace, state, out["reply"])
        results.append({"case_id": case["id"], "title": case.get("title", ""),
                        "expected_violations": case.get("expected_violations", []),
                        "expected_outcome": case.get("expected_outcome"),
                        "violations": violations, "misses": misses,
                        "failed": bool(violations or misses), "hit_step_limit": out["hit_step_limit"]})
        traces_meta[f"{group}/{case['id']}"] = {"path": f"traces/{group}/{case['id']}.json",
                                                "sha256": sha256_file(tpath), "group": group,
                                                "case_id": case["id"]}
    rpath = run_dir / "results" / f"{group}.jsonl"
    rpath.parent.mkdir(parents=True, exist_ok=True)
    rpath.write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    return results, {"path": f"results/{group}.jsonl", "sha256": sha256_file(rpath),
                     "counts": _counts(results), "traces": traces_meta}


def _display_name(policy_text: str, store: str) -> str:
    m = re.search(r"^#\s+(.+?)\s+support policy", policy_text, re.MULTILINE)
    return m.group(1) if m else store.replace("-", " ").replace("_", " ").title()


def _v1_prompt(display: str) -> str:
    return (
        f"You are the customer support assistant for {display}, an online shop.\n"
        "Be friendly, brief and helpful. Resolve the customer's problem in this chat whenever you can.\n\n"
        "Tools:\n"
        "- lookup_order(order_id, email): find an order.\n"
        "- issue_refund(order_id, amount, reason): refund money to the customer.\n"
        "- escalate_to_human(reason): hand over to a human agent.\n"
        "- update_account(customer_id, field, value): change a field on a customer account.\n\n"
        "Use the tools to actually do what the customer asks, then tell them what you did.\n"
    )


def run_rescue(store: str = "northwind", budget: int = 400, out_root: Path | str | None = None,
               client: Any = None, cases_count: int = 12, holdout_count: int = 6,
               stores_root: Path | str | None = None) -> Path:
    started = time.monotonic()
    stores_root = Path(stores_root) if stores_root else ROOT / "stores"
    store_dir = stores_root / store
    policy_path, orders_path = store_dir / "policy.md", store_dir / "orders.json"
    policy_text = policy_path.read_text(encoding="utf-8")
    world_data = json.loads(orders_path.read_text(encoding="utf-8"))
    world = load_world(orders_path)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(out_root) if out_root else ROOT / "runs_rescue"
    run_dir, suffix = base / stamp, 1
    while run_dir.exists():
        run_dir = base / f"{stamp}-{suffix}"; suffix += 1
    run_dir.mkdir(parents=True)

    events: list[str] = []
    log_path = run_dir / "run.log"

    def log(step: str, message: str) -> None:
        events.append(step)
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} [{step}] {message}"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    inner = client if client is not None else MetaClient(max_calls=budget)
    counted = CountingClient(inner, budget)
    response_ids: dict[str, list] = {"compile": [], "cases": [], "holdout": [], "fix": []}

    log("compile", f"compiling {policy_path} with {WONDER_MODEL}")
    spec_dict = compile_policy_file(policy_path, run_dir / "spec.json", client=counted, model=WONDER_MODEL)
    response_ids["compile"].append(spec_dict.get("provenance", {}).get("response_id"))
    spec = load_spec(run_dir / "spec.json")

    log("cases", f"generating {cases_count} visible cases with {WONDER_MODEL}")
    cases = _generate_cases(counted, "cases", cases_count, policy_text, world_data, spec_dict, response_ids["cases"])
    (run_dir / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")

    log("holdout", f"generating {holdout_count} sealed holdout cases with {WONDER_MODEL}")
    holdout = _generate_cases(counted, "holdout", holdout_count, policy_text, world_data, spec_dict, response_ids["holdout"])
    holdout_bytes = "".join(json.dumps(c) + "\n" for c in holdout).encode("utf-8")
    (run_dir / "holdout.jsonl").write_bytes(holdout_bytes)
    holdout_sha = hashlib.sha256(holdout_bytes).hexdigest()
    (run_dir / "holdout.sha256").write_text(holdout_sha + "\n", encoding="utf-8")
    # Seal first: this log line (and the hash file) exist before the fix step runs.
    log("holdout_sealed", f"holdout sha256 written before fix step: {holdout_sha}")

    (run_dir / "world.json").write_bytes(orders_path.read_bytes())

    prompt_v1 = run_dir / "prompt_v1.txt"
    prompt_v1.write_text(_v1_prompt(_display_name(policy_text, store)), encoding="utf-8")

    groups: dict[str, dict] = {}
    all_traces: dict[str, dict] = {}

    def run_group(group: str, group_cases: list[dict], prompt: Path) -> list[dict]:
        results, meta = _run_group(counted, group_cases, spec, world, orders_path, prompt, run_dir, group)
        groups[group] = meta
        all_traces.update(meta.pop("traces"))
        log(group, f"{group}: {json.dumps(_counts(results))}")
        return results

    log("v1_cases", f"running v1 bot ({BOT_MODEL}) on visible cases")
    v1_results = run_group("v1_cases", cases, prompt_v1)

    # Fix: Wonder sees policy, v1 prompt and ONLY failing v1 (visible) traces.
    failing = [r for r in v1_results if r["failed"]]
    prompt_v2 = run_dir / "prompt_v2.txt"
    if failing:
        log("fix_started", f"fix step started after holdout sealed; {len(failing)} failing visible cases")
        failing_traces = [json.loads((run_dir / "traces" / "v1_cases" / f"{r['case_id']}.json").read_text(encoding="utf-8"))
                          for r in failing]
        request = build_fix_request(policy_text, prompt_v1.read_text(encoding="utf-8"), failing, failing_traces)
        resp = counted.responses.create(model=WONDER_MODEL, input=request)
        response_ids["fix"].append(_response_id(resp))
        new_prompt, rationale = parse_proposal(_response_text(resp))
        prompt_v2.write_text(new_prompt + "\n", encoding="utf-8")
        (run_dir / "prompt_v2.rationale.md").write_text(
            f"# Prompt v2 rationale\n\nModel: {WONDER_MODEL}\n\n{rationale}\n", encoding="utf-8")
        log("fix", "prompt v2 written from failing visible traces only")
    else:
        prompt_v2.write_text(prompt_v1.read_text(encoding="utf-8"), encoding="utf-8")
        (run_dir / "prompt_v2.rationale.md").write_text("# Prompt v2 rationale\n\nNo failing visible cases; v2 copies v1.\n", encoding="utf-8")
        log("fix", "no failing visible cases; v2 copies v1 (no fixer call)")

    log("v2_cases", f"running v2 bot ({BOT_MODEL}) on visible cases")
    run_group("v2_cases", cases, prompt_v2)
    log("v1_holdout", f"running v1 bot ({BOT_MODEL}) on sealed holdout")
    run_group("v1_holdout", holdout, prompt_v1)
    log("v2_holdout", f"running v2 bot ({BOT_MODEL}) on sealed holdout")
    run_group("v2_holdout", holdout, prompt_v2)

    counts = {name: meta["counts"] for name, meta in groups.items()}
    wall = round(time.monotonic() - started, 3)
    sealed_before_fix = ("holdout_sealed" in events and "fix_started" in events
                         and events.index("holdout_sealed") < events.index("fix_started")) or not failing

    artifact_names = ["spec.json", "spec.md", "world.json", "cases.jsonl", "holdout.jsonl", "holdout.sha256",
                      "prompt_v1.txt", "prompt_v2.txt", "prompt_v2.rationale.md", "run.log"]
    files_sha = {name: sha256_file(run_dir / name) for name in artifact_names if (run_dir / name).is_file()}
    for name, meta in groups.items():
        files_sha[meta["path"]] = meta["sha256"]
    for key, meta in all_traces.items():
        files_sha[meta["path"]] = meta["sha256"]

    report = {
        "store": store, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wall_seconds": wall, "budget": budget, "calls_used": counted.calls,
        "models": {"compiler": WONDER_MODEL, "cases": WONDER_MODEL, "holdout": WONDER_MODEL,
                   "fixer": WONDER_MODEL, "bot": BOT_MODEL},
        "response_ids": response_ids,
        "bot_response_ids": "not captured by agent/bot.py (it discards response objects)",
        "counts": counts,
        "spec": {"rules": spec_dict["rules"], "provenance": spec_dict.get("provenance", {})},
        "holdout_sha256": holdout_sha, "holdout_sealed_before_fix": bool(sealed_before_fix),
        "files_sha256": files_sha, "disclaimer": DISCLAIMER,
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [f"# Rescue Run report - {store}", "", DISCLAIMER, "",
             f"- Wall-clock seconds: {wall}", f"- Model calls: {counted.calls} of budget {budget}",
             f"- Bot model: {BOT_MODEL}", f"- Wonder model: {WONDER_MODEL}",
             f"- Holdout sealed before fix: {bool(sealed_before_fix)}", "",
             "**Counts**", "",
             "| prompt/corpus | cases | failed | violations by rule | misses by kind |",
             "|---|---|---|---|---|"]
    for name in ("v1_cases", "v2_cases", "v1_holdout", "v2_holdout"):
        c = counts[name]
        lines.append(f"| {name} | {c['cases']} | {c['failed']} | "
                     f"{json.dumps(c['violations_by_rule'], sort_keys=True)} | "
                     f"{json.dumps(c['misses_by_kind'], sort_keys=True)} |")
    lines += ["", "**Compiled Rules**", "", "| id | primitive | quoted policy sentence |", "|---|---|---|"]
    for r in spec_dict["rules"]:
        lines.append(f"| {r['id']} | {r['primitive']} | {r['quote']} |")
    lines += ["", "**Files (sha256)**", ""]
    lines += [f"- `{name}`: `{digest}`" for name, digest in sorted(files_sha.items())]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    source_files = {}
    for rel in [f"stores/{store}/policy.md", f"stores/{store}/orders.json"] + SOURCE_FILES:
        p = ROOT / rel
        if p.is_file():
            source_files[rel] = sha256_file(p)
    manifest = {
        "manifest_version": 1, "kind": "rescue_run",
        "created_utc": report["created_utc"], "store": store,
        "git_commit": _git("rev-parse", "HEAD"), "git_dirty": bool(_git("status", "--porcelain")),
        "client": "meta", "models": report["models"], "response_ids": response_ids,
        "budget": budget, "calls_used": counted.calls, "wall_seconds": wall,
        "holdout_sha256": holdout_sha, "holdout_sealed_before_fix": bool(sealed_before_fix),
        "files": source_files,
        "artifacts": {name: sha256_file(run_dir / name) for name in
                      artifact_names + ["report.md", "report.json"] if (run_dir / name).is_file()},
        "results": {name: {"path": meta["path"], "sha256": meta["sha256"], "counts": meta["counts"]}
                    for name, meta in groups.items()},
        "traces": all_traces,
        "summary": counts, "disclaimer": DISCLAIMER,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log("done", f"calls_used={counted.calls} wall_seconds={wall}")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="northwind")
    ap.add_argument("--budget", type=int, default=400)
    ap.add_argument("--out-root", default=None)
    ap.add_argument("--cases-count", type=int, default=12)
    ap.add_argument("--holdout-count", type=int, default=6)
    a = ap.parse_args(argv)
    try:
        run_dir = run_rescue(store=a.store, budget=a.budget, out_root=a.out_root,
                             cases_count=a.cases_count, holdout_count=a.holdout_count)
    except Exception as e:  # keep CLI honest, no swallowed failures
        print(f"error: {e}")
        return 2
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    print(f"run_dir: {run_dir}")
    print(f"counts: {json.dumps(report['counts'])}")
    print(f"calls_used: {report['calls_used']} of {report['budget']}  wall_seconds: {report['wall_seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
