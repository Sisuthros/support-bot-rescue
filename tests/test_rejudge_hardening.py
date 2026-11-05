import hashlib
import json
import shutil
from pathlib import Path

from rescue.rejudge import _counts, rejudge
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


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _sync_group_counts(run_dir, group, rows):
    counts = _counts(rows)
    manifest_path = run_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    manifest["results"][group]["counts"] = counts
    manifest["summary"][group] = counts
    _save_json(manifest_path, manifest)
    report_path = run_dir / "report.json"
    report = _load_json(report_path)
    report["counts"][group] = counts
    _save_json(report_path, report)


def _strip_recorded_sha(run_dir, filename):
    manifest_path = run_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    if isinstance(manifest.get("artifacts"), dict):
        manifest["artifacts"].pop(filename, None)
    _save_json(manifest_path, manifest)
    report_path = run_dir / "report.json"
    report = _load_json(report_path)
    if isinstance(report.get("files_sha256"), dict):
        report["files_sha256"].pop(filename, None)
    _save_json(report_path, report)


def _falsify_expectation_consistently(run_dir, filename, groups):
    """Rewrite one expectation and its results rows/counts/shas consistently,
    leaving only the stripped sha records as evidence of tampering."""
    definitions_path = run_dir / filename
    definitions = read_jsonl(definitions_path)
    target = next(c for c in definitions if c.get("expected_outcome", {}).get("refund"))
    target["expected_outcome"] = {"refund": 0.01}
    definitions_path.write_bytes(
        "".join(json.dumps(c) + "\n" for c in definitions).encode("utf-8"))
    for group in groups:
        rows = read_jsonl(run_dir / "results" / f"{group}.jsonl")
        row = next(r for r in rows if r["case_id"] == target["id"])
        row["expected_outcome"] = {"refund": 0.01}
        write_results(run_dir, group, rows)
        _sync_group_counts(run_dir, group, rows)
    if filename == "holdout.jsonl":
        digest = sha256_file(definitions_path)
        (run_dir / "holdout.sha256").write_text(digest + "\n", encoding="utf-8")
        report_path = run_dir / "report.json"
        report = _load_json(report_path)
        report["holdout_sha256"] = digest
        _save_json(report_path, report)
    _strip_recorded_sha(run_dir, filename)
    return target["id"]


def test_rejudge_fails_closed_when_cases_sha_recorded_nowhere(tmp_path):
    run_dir = copy_run(tmp_path)
    _falsify_expectation_consistently(run_dir, "cases.jsonl", ("v1_cases", "v2_cases"))
    problems = rejudge(run_dir)
    assert problems == ["cases.jsonl present but its sha256 is recorded in neither "
                        "manifest artifacts nor report files_sha256"], problems


def test_rejudge_fails_closed_when_holdout_sha_recorded_nowhere(tmp_path):
    run_dir = copy_run(tmp_path)
    _falsify_expectation_consistently(run_dir, "holdout.jsonl", ("v1_holdout", "v2_holdout"))
    problems = rejudge(run_dir)
    assert problems == ["holdout.jsonl present but its sha256 is recorded in neither "
                        "manifest artifacts nor report files_sha256"], problems


def test_rejudge_detects_case_id_in_both_visible_and_holdout(tmp_path):
    run_dir = copy_run(tmp_path)
    visible = read_jsonl(run_dir / "cases.jsonl")[0]
    holdout_path = run_dir / "holdout.jsonl"
    with holdout_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(visible) + "\n")
    digest = sha256_file(holdout_path)
    (run_dir / "holdout.sha256").write_text(digest + "\n", encoding="utf-8")
    manifest_path = run_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    manifest["artifacts"]["holdout.jsonl"] = digest
    _save_json(manifest_path, manifest)
    report_path = run_dir / "report.json"
    report = _load_json(report_path)
    report["files_sha256"]["holdout.jsonl"] = digest
    report["holdout_sha256"] = digest
    _save_json(report_path, report)
    problems = rejudge(run_dir)
    assert any(f"case id {visible['id']} appears in both the visible and the sealed holdout set"
               in p for p in problems), problems
