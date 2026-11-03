"""Offline re-judge of a Rescue Run: re-run spec_judge on stored traces and
confirm every count in report.json. No network, no model calls.

Usage: py -3 -m rescue.rejudge runs_rescue/<timestamp>
Prints OK or MISMATCH lines; exit 0 only if everything matches.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compiler.extend import checker_sha256, load_approved_proposals  # noqa: E402
from compiler.spec_judge import judge_stored_trace, load_spec  # noqa: E402
from sandbox.tools import load_world  # noqa: E402
from verifier.outcomes import check_outcome  # noqa: E402
from verify_manifest import sha256_file  # noqa: E402

GROUPS = ("v1_cases", "v2_cases", "v1_holdout", "v2_holdout")


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


def rejudge(run_dir: Path | str, extensions=None) -> list[str]:
    """Return problem lines; empty means every count matches."""
    run_dir = Path(run_dir)
    problems: list[str] = []
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if extensions is None and (run_dir / "extensions").is_dir():
        extensions = load_approved_proposals(run_dir / "extensions")
    recorded_ext = json.loads((run_dir / "spec.json").read_text(encoding="utf-8")).get(
        "provenance", {}).get("extensions") or []
    loaded_ext = {(r.get("primitive"), checker_sha256(r.get("checker_source") or "")) for r in extensions or []}
    for ext in recorded_ext:
        if (ext.get("name"), ext.get("checker_sha256")) not in loaded_ext:
            problems.append(f"extension {ext.get('name')} with checker {ext.get('checker_sha256')} "
                            "is recorded in spec.json but not present in the run's extensions/")
    spec = load_spec(run_dir / "spec.json", extensions=extensions)
    local_world = run_dir / "world.json"
    orders_path = local_world if local_world.is_file() else ROOT / "stores" / report["store"] / "orders.json"
    world = load_world(orders_path)

    holdout_bytes = (run_dir / "holdout.jsonl").read_bytes()
    actual_holdout = hashlib.sha256(holdout_bytes).hexdigest()
    recorded = (run_dir / "holdout.sha256").read_text(encoding="utf-8").strip()
    if actual_holdout != recorded or actual_holdout != report.get("holdout_sha256"):
        problems.append(f"holdout sha256 mismatch: file={actual_holdout} recorded={recorded}")

    for group in GROUPS:
        meta = manifest["results"][group]
        rpath = run_dir / meta["path"]
        if sha256_file(rpath) != meta["sha256"]:
            problems.append(f"{group}: results file sha256 mismatch")
            continue
        stored = {r["case_id"]: r for r in map(json.loads, rpath.read_text(encoding="utf-8").splitlines()) if r}
        recomputed = []
        for key, tmeta in sorted(manifest["traces"].items()):
            if tmeta["group"] != group:
                continue
            tpath = run_dir / tmeta["path"]
            if sha256_file(tpath) != tmeta["sha256"]:
                problems.append(f"{group}/{tmeta['case_id']}: trace sha256 mismatch")
                continue
            payload = json.loads(tpath.read_text(encoding="utf-8"))
            old = stored.get(tmeta["case_id"])
            if old is None:
                problems.append(f"{group}/{tmeta['case_id']}: missing from results")
                continue
            violations = judge_stored_trace(spec, payload, world)
            state = {"today": world["today"], "orders": world["orders"],
                     **payload.get("final_state", {})}
            misses = check_outcome(old.get("expected_outcome"), payload.get("trace") or [], state,
                                   payload.get("reply") or "")
            if violations != old["violations"]:
                problems.append(f"{group}/{tmeta['case_id']}: recomputed violations differ from stored results")
            if misses != old["misses"]:
                problems.append(f"{group}/{tmeta['case_id']}: recomputed misses differ from stored results")
            recomputed.append({**old, "violations": violations, "misses": misses,
                               "failed": bool(violations or misses)})
        counts = _counts(recomputed)
        if counts != report["counts"].get(group):
            problems.append(f"{group}: counts {counts} != report {report['counts'].get(group)}")
        if counts != meta["counts"]:
            problems.append(f"{group}: counts {counts} != manifest {meta['counts']}")
        if counts != manifest["summary"].get(group):
            problems.append(f"{group}: counts {counts} != manifest summary {manifest['summary'].get(group)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print(__doc__)
        return 2
    run_dir = Path(argv[0])
    try:
        problems = rejudge(run_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"MISMATCH: cannot rejudge {run_dir}: {e}")
        return 1
    if problems:
        for p in problems:
            print(f"MISMATCH {p}")
        return 1
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    for group in GROUPS:
        print(f"OK {group}: {json.dumps(report['counts'][group], sort_keys=True)}")
    print("OK all counts in report.json match re-judged stored traces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
