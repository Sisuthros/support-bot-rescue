import hashlib
import json
import shutil
from pathlib import Path

from rescue.rejudge import rejudge
from verify_manifest import sha256_file

ROOT = Path(__file__).resolve().parent.parent
SOURCE_RUN = ROOT / "runs_rescue" / "20261102T165939Z"


def copy_run(tmp_path):
    dst = tmp_path / "run"
    shutil.copytree(SOURCE_RUN, dst)
    return dst


def read_jsonl(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_results(run_dir, group, rows):
    rpath = run_dir / "results" / f"{group}.jsonl"
    rpath.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["results"][group]["sha256"] = sha256_file(rpath)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_rejudge_untampered_copy_is_ok(tmp_path):
    assert rejudge(copy_run(tmp_path)) == []


def test_rejudge_detects_altered_expected_outcome_with_consistent_sha_and_counts(tmp_path):
    run_dir = copy_run(tmp_path)
    rows = read_jsonl(run_dir / "results" / "v1_cases.jsonl")
    target = next(r for r in rows if r.get("expected_outcome", {}).get("refund"))
    # A tiny expectation the stored refunds already satisfy: recomputation
    # under the tampered expectation still matches the stored misses/counts.
    target["expected_outcome"] = {"refund": 0.01}
    write_results(run_dir, "v1_cases", rows)
    problems = rejudge(run_dir)
    assert any("expected_outcome" in p and target["case_id"] in p for p in problems), problems


def test_rejudge_detects_duplicate_result_row(tmp_path):
    run_dir = copy_run(tmp_path)
    rows = read_jsonl(run_dir / "results" / "v1_cases.jsonl")
    rows.append(dict(rows[0]))
    write_results(run_dir, "v1_cases", rows)
    problems = rejudge(run_dir)
    assert any("duplicate" in p and "v1_cases" in p for p in problems), problems


def test_rejudge_detects_extra_result_row_without_trace(tmp_path):
    run_dir = copy_run(tmp_path)
    rows = read_jsonl(run_dir / "results" / "v1_cases.jsonl")
    rows.append({**rows[0], "case_id": "extra-row-no-trace"})
    write_results(run_dir, "v1_cases", rows)
    problems = rejudge(run_dir)
    assert any("extra-row-no-trace" in p for p in problems), problems


def test_rejudge_detects_missing_case_when_result_and_trace_entries_removed(tmp_path):
    run_dir = copy_run(tmp_path)
    rows = read_jsonl(run_dir / "results" / "v1_cases.jsonl")
    removed = rows.pop(0)
    write_results(run_dir, "v1_cases", rows)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["traces"].pop(f"v1_cases/{removed['case_id']}", None)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    problems = rejudge(run_dir)
    assert any(removed["case_id"] in p for p in problems), problems


def test_rejudge_detects_duplicate_case_id_in_original_cases(tmp_path):
    run_dir = copy_run(tmp_path)
    cases_path = run_dir / "cases.jsonl"
    lines = cases_path.read_text(encoding="utf-8").splitlines()
    lines.append(lines[0])
    cases_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Rewrite the recorded artifact hashes consistently, as a tamperer would.
    digest = sha256_file(cases_path)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(manifest.get("artifacts"), dict) and "cases.jsonl" in manifest["artifacts"]:
        manifest["artifacts"]["cases.jsonl"] = digest
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report_path = run_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if isinstance(report.get("files_sha256"), dict) and "cases.jsonl" in report["files_sha256"]:
        report["files_sha256"]["cases.jsonl"] = digest
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    problems = rejudge(run_dir)
    assert any("duplicate" in p and "cases" in p for p in problems), problems
