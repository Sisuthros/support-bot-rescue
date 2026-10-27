"""Run a corpus against the support bot, judge it with the verifier, seal the run in a manifest.

Usage: py -3 run.py --client scripted|meta --corpus corpus/named.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.bot import PROMPT_PATH, run_conversation
from agent.client import DEFAULT_MODEL, MetaAPIError, MetaClient, ScriptedClient
from sandbox.tools import ORDERS_PATH, Sandbox
from verifier.rules import VERIFIER_VERSION, check_all
from verifier.outcomes import check_outcome
from verify_manifest import ROOT, sha256_file

POLICY_PATH = ROOT / "maple" / "policy.md"
SCRIPTED_PATH = ROOT / "corpus" / "scripted_replies.json"
# Scripted fallback for cases without a script: a compliant bot that escalates.
DEFAULT_SCRIPT = [
    [{"type": "function_call", "name": "escalate_to_human", "arguments": {"reason": "cannot verify or action this request"}}],
    [{"type": "message", "text": "I have passed this to a human colleague who will follow up."}],
]


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _test_ids() -> list[str]:
    p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"], cwd=ROOT,
                       capture_output=True, text=True)
    return [ln for ln in p.stdout.splitlines() if "::" in ln]


def run_corpus(corpus_path: Path | str, client_name: str, client_factory, model: str, out_root: Path | str,
               collect_tests: bool = True, prompt_path: Path | str = PROMPT_PATH, firewall: bool = False) -> Path:
    """client_factory(case_id) -> client. Returns the manifest path."""
    corpus_path = Path(corpus_path).resolve()
    prompt_path = Path(prompt_path).resolve()
    cases = [json.loads(ln) for ln in corpus_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    run_dir = Path(out_root) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (run_dir / "traces").mkdir(parents=True)

    results, traces = [], {}
    by_rule: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for case in cases:
        sb = Sandbox()
        out = run_conversation(client_factory(case["id"]), sb, case["turns"], model=model, prompt_path=prompt_path,
                               firewall=firewall)
        state = sb.state()
        violations = check_all(sb.trace, state, out["reply"])
        misses = check_outcome(case.get("expected_outcome"), sb.trace, state, out["reply"])
        tpath = run_dir / "traces" / f"{case['id']}.json"
        tpath.write_text(json.dumps({
            "case_id": case["id"], "turns": case["turns"], "trace": sb.trace, "reply": out["reply"],
            "final_state": {k: state[k] for k in ("refunds", "escalations", "account_changes")},
        }, indent=2), encoding="utf-8")
        traces[case["id"]] = {"path": f"traces/{case['id']}.json", "sha256": sha256_file(tpath)}
        results.append({"case_id": case["id"], "title": case["title"],
                        "expected_violations": case.get("expected_violations", []),
                        "expected_outcome": case.get("expected_outcome"),
                        "violations": violations, "misses": misses,
                        "failed": bool(violations or misses), "hit_step_limit": out["hit_step_limit"]})
        for v in violations:
            by_rule[v["rule"]] = by_rule.get(v["rule"], 0) + 1
        for miss in misses:
            by_kind[miss["kind"]] = by_kind.get(miss["kind"], 0) + 1
    rpath = run_dir / "results.jsonl"
    rpath.write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")

    inputs = [POLICY_PATH, ORDERS_PATH, prompt_path, corpus_path] + ([SCRIPTED_PATH] if client_name == "scripted" else [])
    manifest = {
        "manifest_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "client": client_name,
        "firewall": bool(firewall),
        "prompt_path": _rel(prompt_path),
        "prompt_sha256": sha256_file(prompt_path),
        "model": model if client_name == "meta" else "scripted",
        "seed": "unavailable",
        "verifier_version": VERIFIER_VERSION,
        "test_ids": _test_ids() if collect_tests else [],
        "files": {_rel(p): sha256_file(p) for p in inputs},
        "results_sha256": sha256_file(rpath),
        "traces": traces,
        "summary": {"cases": len(results), "failed": sum(r["failed"] for r in results),
                    "violations_by_rule": by_rule, "misses_by_kind": by_kind},
    }
    mpath = run_dir / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return mpath


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", choices=["scripted", "meta"], required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--prompt", default=str(PROMPT_PATH), help="system prompt file (default: agent/prompts/v1.txt)")
    ap.add_argument("--max-calls", type=int, default=60, help="model call budget for the whole run (meta)")
    ap.add_argument("--firewall", action="store_true", help="route refunds through the deterministic refund authority")
    ap.add_argument("--out", default=str(ROOT / "runs"))
    a = ap.parse_args(argv)

    if a.client == "scripted":
        scripts = json.loads(SCRIPTED_PATH.read_text(encoding="utf-8"))
        factory = lambda cid: ScriptedClient(scripts.get(cid, DEFAULT_SCRIPT))  # noqa: E731
    else:
        try:
            shared = MetaClient(max_calls=a.max_calls)
        except MetaAPIError as e:
            print(f"error: {e}")
            return 2
        factory = lambda cid: shared  # noqa: E731
    try:
        mpath = run_corpus(a.corpus, a.client, factory, a.model, a.out, prompt_path=a.prompt, firewall=a.firewall)
    except (MetaAPIError, RuntimeError) as e:
        print(f"run aborted: {e}")
        return 2
    m = json.loads(mpath.read_text(encoding="utf-8"))
    print(f"manifest: {_rel(mpath)}")
    print(f"summary: {json.dumps(m['summary'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
