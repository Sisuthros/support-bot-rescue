import hashlib
import json
from pathlib import Path

import pytest

from agent.client import ScriptedClient
from fixer.fix import FIXER_MODEL, fix_run
import fixer.fix as fix_module
from verify_manifest import ROOT, recheck
import run as run_module

MODEL_OUTPUT = """<<<PROMPT>>>
You are the customer support assistant for Maple & Co. Always verify first.
<<<RATIONALE>>>
Tightens delivery-window and cap checks before any refund.
Targets: R2, R3
<<<END>>>"""


def make_run_dir(base: Path) -> Path:
    run_dir = base / "run"
    (run_dir / "traces").mkdir(parents=True)
    results = [
        {"case_id": "n03_bad", "title": "old order", "expected_violations": ["R2"],
         "violations": [{"rule": "R2", "trace_index": 1, "detail": "too old"}], "failed": True, "hit_step_limit": False},
        {"case_id": "n04_bad", "title": "big refund", "expected_violations": ["R3"],
         "violations": [{"rule": "R3", "trace_index": 1, "detail": "over cap"}], "failed": True, "hit_step_limit": False},
        {"case_id": "n01_ok", "title": "fine", "expected_violations": [],
         "violations": [], "failed": False, "hit_step_limit": False},
    ]
    (run_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps({"files": {"corpus/named.jsonl": "x"}}), encoding="utf-8")
    for cid, marker in [("n03_bad", "FAILMARK-N03"), ("n04_bad", "FAILMARK-N04"), ("n01_ok", "PASSMARK-N01")]:
        (run_dir / "traces" / f"{cid}.json").write_text(
            json.dumps({"case_id": cid, "turns": [marker], "trace": [], "reply": marker, "final_state": {}}),
            encoding="utf-8")
    return run_dir


def scripted_client():
    return ScriptedClient([[{"type": "message", "text": MODEL_OUTPUT}]])


def test_fixer_writes_v2_from_scripted_output(tmp_path):
    run_dir = make_run_dir(tmp_path)
    client = scripted_client()
    out_prompt = tmp_path / "agent" / "prompts" / "v2.txt"
    out_rationale = tmp_path / "agent" / "prompts" / "v2.rationale.md"
    got_prompt, got_rationale = fix_run(run_dir, client=client, out_prompt=out_prompt, out_rationale=out_rationale)
    assert (got_prompt, got_rationale) == (out_prompt, out_rationale)
    assert out_prompt.read_text(encoding="utf-8").strip() == "You are the customer support assistant for Maple & Co. Always verify first."
    rationale = out_rationale.read_text(encoding="utf-8")
    assert "Targeted rules: R2, R3" in rationale and "Targets: R2, R3" in rationale
    assert client.requests[0]["model"] == FIXER_MODEL == "muse-wonder-1.0"
    request = client.requests[0]["input"]
    assert "FAILMARK-N03" in request and "FAILMARK-N04" in request  # failing traces are given to the model
    assert "PASSMARK-N01" not in request  # passing traces are not
    assert "30-day window" in request  # policy is given to the model


def test_fixer_never_opens_holdout(tmp_path, monkeypatch):
    run_dir = make_run_dir(tmp_path)
    real_read_text, real_read_bytes = Path.read_text, Path.read_bytes

    def guarded(self, *args, **kwargs):
        assert "holdout" not in str(self), f"fixer opened the holdout file: {self}"
        return real_read_text(self, *args, **kwargs)

    def guarded_bytes(self, *args, **kwargs):
        assert "holdout" not in str(self), f"fixer opened the holdout file: {self}"
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    monkeypatch.setattr(Path, "read_bytes", guarded_bytes)
    fix_run(run_dir, client=scripted_client(), out_prompt=tmp_path / "v2.txt", out_rationale=tmp_path / "v2.md")
    assert (tmp_path / "v2.txt").is_file()


def test_fixer_refuses_a_holdout_run(tmp_path):
    run_dir = make_run_dir(tmp_path)
    (run_dir / "manifest.json").write_text(json.dumps({"files": {"corpus/holdout.jsonl": "x"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="holdout"):
        fix_run(run_dir, client=scripted_client(), out_prompt=tmp_path / "v2.txt", out_rationale=tmp_path / "v2.md")
    assert not (tmp_path / "v2.txt").exists()


def test_run_prompt_manifest_round_trip(tmp_path):
    prompt = tmp_path / "custom_prompt.txt"
    prompt.write_text("Custom prompt for the round-trip test.\n", encoding="utf-8")
    out = tmp_path / "runs"
    assert run_module.main(["--client", "scripted", "--corpus", str(ROOT / "corpus" / "named.jsonl"),
                            "--prompt", str(prompt), "--out", str(out)]) == 0
    manifests = list(out.glob("*/manifest.json"))
    assert len(manifests) == 1
    m = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert m["prompt_path"].endswith("custom_prompt.txt") and (ROOT / m["prompt_path"]).resolve() == prompt.resolve()
    assert m["prompt_sha256"] == hashlib.sha256(prompt.read_bytes()).hexdigest()
    assert m["files"][m["prompt_path"]] == m["prompt_sha256"]
    assert recheck(manifests[0]) == []


def test_fixer_receives_miss_traces_and_counts_misses(tmp_path):
    run_dir = make_run_dir(tmp_path)
    # Add a miss-only failure: no violation, but an eligible refund was escalated away.
    results_path = run_dir / "results.jsonl"
    results = [json.loads(ln) for ln in results_path.read_text(encoding="utf-8").splitlines()]
    results.append({"case_id": "u01_missed", "title": "eligible refund escalated", "expected_violations": [],
                    "expected_outcome": {"refund": 59.0}, "violations": [],
                    "misses": [{"kind": "U1", "trace_index": None, "detail": "expected refund $59.00"}],
                    "failed": True, "hit_step_limit": False})
    results_path.write_text("".join(json.dumps(r) + "\n" for r in results), encoding="utf-8")
    (run_dir / "traces" / "u01_missed.json").write_text(
        json.dumps({"case_id": "u01_missed", "turns": ["MISSMARK-U01"], "trace": [], "reply": "MISSMARK-U01",
                    "final_state": {}}), encoding="utf-8")
    client = scripted_client()
    out_prompt, out_rationale = fix_run(run_dir, client=client, out_prompt=tmp_path / "v3.txt",
                                        out_rationale=tmp_path / "v3.rationale.md")
    request = client.requests[0]["input"]
    assert "MISSMARK-U01" in request  # the failing trace for the miss is given to the model
    assert "U1" in request and "both" in request.lower() and "escalating everything" in request
    rationale = out_rationale.read_text(encoding="utf-8")
    assert "Targeted misses: U1" in rationale


def test_fixer_cli_out_derives_rationale_and_starts_from_run_prompt(tmp_path, monkeypatch):
    run_dir = make_run_dir(tmp_path)
    source_prompt = tmp_path / "v2.txt"
    source_prompt.write_text("SOURCE-V2-PROMPT\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps({"files": {"corpus/named.jsonl": "x"}, "prompt_path": str(source_prompt)}), encoding="utf-8")
    client = scripted_client()
    monkeypatch.setattr(fix_module, "MetaClient", lambda **kw: client)
    out = tmp_path / "agent" / "prompts" / "v3.txt"
    assert fix_module.main(["--run", str(run_dir), "--out", str(out)]) == 0
    assert out.is_file() and (tmp_path / "agent" / "prompts" / "v3.rationale.md").is_file()
    assert "SOURCE-V2-PROMPT" in client.requests[0]["input"]  # v3 starts from the run's prompt, not v1
