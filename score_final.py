"""Score the final blind usefulness holdout (k07-k12) against four variants.

Usage:
  py -3 score_final.py --cases <file> --sha256 <hex> [--live] [--max-calls N] [--out runs]

Exit codes:
  0  dry-run plan printed, or live scoring completed and every manifest re-verified
  2  sha256 mismatch (refused before parsing the file), or a live run could not start/finish
  3  the cases file does not match the required k07-k12 schema
  1  live scoring finished but a manifest failed verify_manifest.recheck
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.client import DEFAULT_MODEL, MetaAPIError, MetaClient
from run import run_corpus
from verify_manifest import ROOT, recheck

EXPECTED_IDS = ["k07", "k08", "k09", "k10", "k11", "k12"]

# (variant name, prompt path relative to repo root, firewall on/off)
VARIANTS = [
    ("v1", "agent/prompts/v1.txt", False),
    ("v2", "agent/prompts/v2.txt", False),
    ("v3", "agent/prompts/v3.txt", False),
    ("v1-firewall", "agent/prompts/v1.txt", True),
]


class SchemaError(ValueError):
    """The cases file does not match the required schema."""


def compute_sha256(path: Path | str) -> str:
    """sha256 of the exact file bytes (no newline normalisation)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_cases(data: bytes) -> list[dict]:
    """Validate the sealed-case schema; raise SchemaError on the first problem."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SchemaError(f"INVALID: file is not valid UTF-8: {e}") from None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) != 6:
        raise SchemaError(f"INVALID: expected exactly 6 cases (JSON lines), got {len(lines)}")
    cases: list[dict] = []
    for i, line in enumerate(lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise SchemaError(f"INVALID: line {i}: invalid JSON: {e.msg}") from None
        if not isinstance(obj, dict):
            raise SchemaError(f"INVALID: line {i}: expected a JSON object")
        cases.append(obj)

    seen: dict[str, int] = {}
    for i, case in enumerate(cases, start=1):
        cid = case.get("id")
        if not isinstance(cid, str) or not cid:
            raise SchemaError(f"INVALID: line {i}: id must be a non-empty string")
        if cid in seen:
            raise SchemaError(f"INVALID: duplicate id {cid!r} on lines {seen[cid]} and {i}")
        seen[cid] = i
    unexpected = sorted(set(seen) - set(EXPECTED_IDS))
    if unexpected:
        raise SchemaError(
            f"INVALID: unexpected id {unexpected[0]!r}: ids must be exactly {', '.join(EXPECTED_IDS)}")
    missing = [cid for cid in EXPECTED_IDS if cid not in seen]
    if missing:
        raise SchemaError(
            f"INVALID: missing id {missing[0]!r}: ids must be exactly {', '.join(EXPECTED_IDS)}")

    for case in cases:
        cid = case["id"]
        title = case.get("title")
        if not isinstance(title, str) or not title.strip():
            raise SchemaError(f"INVALID: case {cid}: title must be a non-empty string")
        turns = case.get("turns")
        if not isinstance(turns, list):
            raise SchemaError(f"INVALID: case {cid}: turns must be a non-empty list of non-empty strings")
        if not turns or any(not isinstance(t, str) or not t.strip() for t in turns):
            raise SchemaError(f"INVALID: case {cid}: turns must be a non-empty list of non-empty strings")
        if case.get("expected_violations") != []:
            raise SchemaError(f"INVALID: case {cid}: expected_violations must be []")
        outcome = case.get("expected_outcome")
        if not isinstance(outcome, dict) or not outcome:
            raise SchemaError(
                f"INVALID: case {cid}: expected_outcome must be exactly "
                '{"refund": <number > 0>} or {"escalate": true}')
        keys = set(outcome)
        if keys not in ({"refund"}, {"escalate"}):
            extra = sorted(keys - {"refund", "escalate"}) or sorted(keys)
            raise SchemaError(
                f"INVALID: case {cid}: expected_outcome has extra key(s) {extra}: "
                "no other keys are allowed in expected_outcome")
        if "refund" in outcome:
            amount = outcome["refund"]
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) \
                    or not math.isfinite(amount) or amount <= 0:
                raise SchemaError(
                    f"INVALID: case {cid}: expected_outcome refund must be a number > 0")
        elif outcome.get("escalate") is not True:
            raise SchemaError(
                f"INVALID: case {cid}: expected_outcome escalate must be true")
    return cases


def _print_plan(cases_path: Path, actual: str, case_count: int, max_calls: int) -> None:
    print(f"cases: {cases_path}")
    print(f"sha256: {actual}")
    print(f"case count: {case_count}")
    print(f"max-calls per variant: {max_calls}")
    print(f"max-calls budget: {max_calls} per variant, {max_calls * len(VARIANTS)} total across {len(VARIANTS)} variants")
    print("variants:")
    for name, prompt_rel, firewall in VARIANTS:
        equivalent = (
            f"py -3 run.py --client meta --corpus {cases_path} --model {DEFAULT_MODEL} "
            f"--prompt {prompt_rel} --max-calls {max_calls}"
        ) + (" --firewall" if firewall else "")
        print(f"- {name}: client=meta model={DEFAULT_MODEL} prompt={prompt_rel} firewall={firewall} max_calls={max_calls}")
        print(f"  run.py equivalent: {equivalent}")


def _miss_summary(results: list[dict], kind: str) -> dict:
    case_ids = [r["case_id"] for r in results
                if any(m.get("kind") == kind for m in r.get("misses", []))]
    return {"count": len(case_ids), "case_ids": case_ids}


def _run_live(cases_path: Path, actual: str, cases: list[dict], max_calls: int, out: Path) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_dir = Path(out) / f"final-{timestamp}"
    final_dir.mkdir(parents=True, exist_ok=True)

    variants: dict[str, dict] = {}
    any_verify_problems = False
    for name, prompt_rel, firewall in VARIANTS:
        try:
            client = MetaClient(max_calls=max_calls)
        except (MetaAPIError, RuntimeError, OSError) as e:
            print(f"error: could not construct Meta client for variant {name}: {e}")
            return 2
        try:
            manifest_path = run_corpus(
                cases_path, "meta", lambda cid, shared=client: shared, DEFAULT_MODEL,
                final_dir / name, prompt_path=ROOT / prompt_rel, firewall=firewall)
        except (MetaAPIError, RuntimeError) as e:
            print(f"run aborted: variant {name}: {e}")
            return 2
        problems = recheck(manifest_path)
        if problems:
            any_verify_problems = True
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results = [json.loads(ln) for ln in
                   (manifest_path.parent / "results.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        summary = manifest.get("summary", {})
        variants[name] = {
            "variant": name,
            "prompt": prompt_rel,
            "firewall": firewall,
            "max_calls": max_calls,
            "run_dir": str(manifest_path.parent),
            "manifest": str(manifest_path),
            "violations_by_rule": summary.get("violations_by_rule", {}),
            "U1": _miss_summary(results, "U1"),
            "U2": _miss_summary(results, "U2"),
            "escalations_by_actor": summary.get("escalations_by_actor", {}),
            "verify_result": "OK" if not problems else "MISMATCH",
            "verify_problems": problems,
        }
        print(f"{name}: run_dir={manifest_path.parent} verify={variants[name]['verify_result']}")

    summary_doc = {
        "cases": str(cases_path),
        "cases_sha256": actual,
        "case_count": len(cases),
        "max_calls_per_variant": max_calls,
        "variants": variants,
    }
    (final_dir / "SUMMARY.json").write_text(json.dumps(summary_doc, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        "# Final blind holdout scoring",
        "",
        f"- Cases sha256: `{actual}`",
        f"- Cases: `{cases_path}` ({len(cases)} cases)",
        f"- Max calls per variant: {max_calls}",
        "",
        "| Variant | Prompt | Firewall | Run dir | Violations by rule | U1 (missed refund) | U2 (missed escalation) | Escalations by actor | Verify |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, v in variants.items():
        md_lines.append(
            f"| {name} | {v['prompt']} | {v['firewall']} | {v['run_dir']} | "
            f"{json.dumps(v['violations_by_rule'])} | {v['U1']['count']} {v['U1']['case_ids']} | "
            f"{v['U2']['count']} {v['U2']['case_ids']} | {json.dumps(v['escalations_by_actor'])} | {v['verify_result']} |")
    if any_verify_problems:
        md_lines += ["", "Verify problems:"]
        for name, v in variants.items():
            for problem in v["verify_problems"]:
                md_lines.append(f"- {name}: {problem}")
    (final_dir / "SUMMARY.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"summary: {final_dir / 'SUMMARY.md'}")
    print(f"summary: {final_dir / 'SUMMARY.json'}")
    return 1 if any_verify_problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Score the final blind holdout (k07-k12) for four variants.")
    ap.add_argument("--cases", required=True, help="path to the sealed JSONL cases file")
    ap.add_argument("--sha256", required=True, help="expected sha256 hex of the exact cases file bytes")
    ap.add_argument("--live", action="store_true", help="actually run the Meta client (default: dry-run plan only)")
    ap.add_argument("--max-calls", type=int, default=200, help="model call budget per variant (default: 200)")
    ap.add_argument("--out", default="runs", help="output root for run dirs and SUMMARY files (default: runs)")
    a = ap.parse_args(argv)

    cases_path = Path(a.cases)
    try:
        data = cases_path.read_bytes()
    except OSError as e:
        print(f"error: cannot read cases file {cases_path}: {e}")
        return 2
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != a.sha256.strip().lower():
        print(f"REFUSED: sha256 mismatch: expected {a.sha256.strip().lower()} but file hashes to {actual}")
        return 2

    try:
        cases = validate_cases(data)
    except SchemaError as e:
        print(str(e))
        return 3

    _print_plan(cases_path, actual, len(cases), a.max_calls)
    if not a.live:
        print("dry-run: no client constructed, no network calls; pass --live to score")
        return 0
    return _run_live(cases_path, actual, cases, a.max_calls, Path(a.out))


if __name__ == "__main__":
    sys.exit(main())
