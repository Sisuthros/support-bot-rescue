import ast
import json
import re
import socket
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence" / "5423ab2"
sys.path.insert(0, str(ROOT))

import demo  # noqa: E402


def _runs():
    shown, holdout_ids = [], []
    for run_dir in sorted(EVIDENCE.iterdir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        corpora = [k for k in manifest.get("files", {}) if k.startswith("corpus/") and k.endswith(".jsonl")]
        if any("holdout" in c for c in corpora):
            holdout_ids.append(run_dir.name)
        else:
            shown.append((run_dir, manifest, corpora[0] if corpora else ""))
    return shown, holdout_ids


def _verifier_available():
    if (ROOT.parent / "sbr-5423ab2" / "verify_manifest.py").is_file():
        return True
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--verify", "5423ab2^{commit}"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _independent_counts(run_dir):
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    violations = Counter(v["rule"] for row in rows for v in row.get("violations", []))
    misses = Counter(m["kind"] for row in rows for m in row.get("misses", []))
    failed = sum(1 for row in rows if row.get("failed", bool(row.get("violations") or row.get("misses"))))
    return {"cases": len(rows), "failed": failed, "violations": violations, "misses": misses}


def _parse_summary(out):
    parsed = {}
    pattern = re.compile(
        r"^(v1 \(firewall off\)|v2 \(firewall off\)|v3 \(firewall off\)|v1\+firewall): "
        r"cases=(\d+) failed=(\d+) violations=(\d+)(?: \(([^)]*)\))? misses=(\d+)(?: \(([^)]*)\))?$",
        re.MULTILINE,
    )
    for label, cases, failed, vtotal, vdetail, mtotal, mdetail in pattern.findall(out):
        def parse(detail):
            result = Counter()
            for part in (detail or "").split(","):
                if part.strip():
                    key, value = part.strip().split(":")
                    result[key] = int(value)
            return result
        parsed[label] = {
            "cases": int(cases), "failed": int(failed),
            "violations": parse(vdetail), "misses": parse(mdetail),
            "violations_total": int(vtotal), "misses_total": int(mtotal),
        }
    return parsed


def test_demo_runs_offline_and_prints_independent_counts(monkeypatch, capsys):
    if not _verifier_available():
        pytest.skip("5423ab2 verifier unavailable (no ../sbr-5423ab2 worktree and no git commit 5423ab2)")

    def _no_network(*args, **kwargs):
        raise AssertionError("demo attempted a network connection")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    exit_code = demo.main(["--fast", "--no-color"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "13 of 13 OK" in out

    shown, holdout_ids = _runs()
    assert len(shown) == 13
    for holdout_id in holdout_ids:
        assert holdout_id not in out

    by_key = {}
    for run_dir, manifest, corpus in shown:
        if corpus == "corpus/named.jsonl":
            by_key[(manifest["prompt_path"], bool(manifest["firewall"]))] = run_dir

    expected = {
        "v1 (firewall off)": _independent_counts(by_key[("agent/prompts/v1.txt", False)]),
        "v2 (firewall off)": _independent_counts(by_key[("agent/prompts/v2.txt", False)]),
        "v3 (firewall off)": _independent_counts(by_key[("agent/prompts/v3.txt", False)]),
        "v1+firewall": _independent_counts(by_key[("agent/prompts/v1.txt", True)]),
    }
    parsed = _parse_summary(out)
    assert set(parsed) == set(expected)
    for label, counts in expected.items():
        assert parsed[label]["cases"] == counts["cases"]
        assert parsed[label]["failed"] == counts["failed"]
        assert parsed[label]["violations"] == counts["violations"]
        assert parsed[label]["misses"] == counts["misses"]
        assert parsed[label]["violations_total"] == sum(counts["violations"].values())
        assert parsed[label]["misses_total"] == sum(counts["misses"].values())


def test_demo_uses_only_standard_library():
    tree = ast.parse((ROOT / "demo.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= sys.stdlib_module_names
