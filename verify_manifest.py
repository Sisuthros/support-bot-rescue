"""Independently recompute every hash in a run manifest and re-run the verifier on the stored traces.

Usage: py -3 verify_manifest.py runs/<run>/manifest.json   (exit 0 = consistent, 1 = mismatch)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from sandbox.tools import load_world
from verifier.rules import VERIFIER_VERSION, check_all
from verifier.outcomes import check_outcome

ROOT = Path(__file__).resolve().parent


def sha256_file(path: Path) -> str:
    # CRLF -> LF first, so a Windows working copy and a clean clone hash the same.
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def prompt_rationale_path(prompt_path: Path | str) -> Path:
    prompt_path = Path(prompt_path)
    return prompt_path.with_name(f"{prompt_path.stem}.rationale.md")


def parse_prompt_author_model(prompt_path: Path | str) -> str | None:
    """Model named on the prompt rationale's 'Model: ...' line, else None."""
    rationale = prompt_rationale_path(prompt_path)
    if not rationale.is_file():
        return None
    match = re.search(r"^Model:\s*(.+?)\s*$", rationale.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def escalations_by_actor(escalations) -> dict:
    counts = {"bot": 0, "authority": 0}
    for entry in escalations or []:
        actor = entry.get("actor") if isinstance(entry, dict) else None
        counts["authority" if actor == "authority" else "bot"] += 1
    return counts


def recheck(manifest_path: Path | str) -> list[str]:
    """Return a list of problems; empty means the manifest holds."""
    mp = Path(manifest_path)
    run_dir = mp.parent
    m = json.loads(mp.read_text(encoding="utf-8"))
    problems: list[str] = []

    def check(label: str, path: Path, expected: str) -> bool:
        if not path.is_file():
            problems.append(f"{label}: missing file {path}")
            return False
        if sha256_file(path) != expected:
            problems.append(f"{label}: sha256 mismatch")
            return False
        return True

    for rel, digest in m["files"].items():
        check(rel, ROOT / rel, digest)
    check("results.jsonl", run_dir / "results.jsonl", m["results_sha256"])
    if m["verifier_version"] != VERIFIER_VERSION:
        problems.append(f"verifier version {m['verifier_version']} != {VERIFIER_VERSION}")
    prompt_rel = m.get("prompt_path")
    if prompt_rel:
        prompt_path = Path(prompt_rel)
        if not prompt_path.is_absolute():
            prompt_path = ROOT / prompt_path
        expected_model = parse_prompt_author_model(prompt_path)
        if m.get("prompt_author_model") != expected_model:
            problems.append(
                f"prompt_author_model {m.get('prompt_author_model')!r} != {expected_model!r} from prompt rationale")

    world = load_world(ROOT / "maple" / "orders.json")
    results = {}
    rp = run_dir / "results.jsonl"
    if rp.is_file():
        results = {r["case_id"]: r for r in map(json.loads, rp.read_text(encoding="utf-8").splitlines())}
    # Expected outcomes come from the (hash-checked) corpus in the manifest,
    # falling back to the copy stored in results.jsonl.
    expectations: dict[str, object] = {}
    corpus_rels = [k for k in m.get("files", {}) if k.startswith("corpus/") and k.endswith(".jsonl")]
    for rel in corpus_rels:
        corpus_path = ROOT / rel
        if corpus_path.is_file():
            for line in corpus_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    case = json.loads(line)
                    expectations[case["id"]] = case.get("expected_outcome")
    failed = 0
    failed_violations_only = 0
    by_rule: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    esc_totals = {"bot": 0, "authority": 0}
    firewall = bool(m.get("firewall"))
    for cid, t in m["traces"].items():
        if not check(f"trace {cid}", run_dir / t["path"], t["sha256"]):
            continue
        tr = json.loads((run_dir / t["path"]).read_text(encoding="utf-8"))
        state = {"today": world["today"], "orders": world["orders"], **tr["final_state"]}
        violations = check_all(tr["trace"], state, tr["reply"])
        if cid not in results or results[cid]["violations"] != violations:
            problems.append(f"trace {cid}: recomputed violations differ from results.jsonl")
        expected_outcome = expectations.get(cid, results.get(cid, {}).get("expected_outcome"))
        misses = check_outcome(expected_outcome, tr["trace"], state, tr["reply"])
        if cid not in results or results[cid].get("misses", []) != misses:
            problems.append(f"trace {cid}: recomputed misses differ from results.jsonl")
        esc = escalations_by_actor(tr["final_state"].get("escalations", []))
        if cid not in results or results[cid].get("escalations_by_actor") != esc:
            problems.append(f"trace {cid}: recomputed escalations_by_actor differ from results.jsonl")
        for actor in esc_totals:
            esc_totals[actor] += esc[actor]
        if firewall:
            for entry in tr["trace"]:
                if not isinstance(entry, dict) or entry.get("name") != "issue_refund":
                    continue
                result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
                if result.get("ok") is True and entry.get("actor") != "authority":
                    problems.append(
                        f"trace {cid}: firewall is true but a successful issue_refund "
                        f"at trace index {entry.get('index')} was not filed by actor 'authority'")
        elif any(isinstance(e, dict) and e.get("name") == "propose_refund" for e in tr["trace"]):
            problems.append(f"trace {cid}: firewall is false but trace contains propose_refund")
        failed += bool(violations or misses)
        failed_violations_only += bool(violations)
        for v in violations:
            by_rule[v["rule"]] = by_rule.get(v["rule"], 0) + 1
        for miss in misses:
            by_kind[miss["kind"]] = by_kind.get(miss["kind"], 0) + 1
    expected = {"cases": len(m["traces"]), "failed": failed,
                "violations_by_rule": by_rule, "misses_by_kind": by_kind,
                "escalations_by_actor": esc_totals}
    if "misses_by_kind" not in m["summary"]:
        # Legacy manifests predate usefulness tracking; compare only what they recorded.
        expected = {"cases": expected["cases"], "failed": failed_violations_only,
                    "violations_by_rule": by_rule}
    if m["summary"] != expected:
        problems.append(f"summary differs from recomputation: {m['summary']} vs {expected}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    problems = recheck(argv[0])
    if problems:
        print("MISMATCH")
        for p in problems:
            print(" -", p)
        return 1
    m = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    print(f"OK: {len(m['files']) + 1} file hashes, {len(m['traces'])} traces re-verified, verifier {VERIFIER_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
