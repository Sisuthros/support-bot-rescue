import json
from pathlib import Path

from agent.client import ScriptedClient
from run import DEFAULT_SCRIPT, SCRIPTED_PATH, run_corpus
from verify_manifest import ROOT, main, recheck


def make_run(tmp_path):
    scripts = json.loads(SCRIPTED_PATH.read_text(encoding="utf-8"))
    return run_corpus(ROOT / "corpus" / "named.jsonl", "scripted",
                      lambda cid: ScriptedClient(scripts.get(cid, DEFAULT_SCRIPT)), "scripted", tmp_path,
                      collect_tests=False)


def test_round_trip_and_summary(tmp_path):
    mp = make_run(tmp_path)
    assert recheck(mp) == [] and main([str(mp)]) == 0
    m = json.loads(mp.read_text(encoding="utf-8"))
    assert m["seed"] == "unavailable" and m["summary"]["cases"] == 10
    assert m["summary"]["violations_by_rule"] == {"R1": 1, "R3": 1, "R6": 1}  # the three naive scripts


def test_tampered_trace_is_detected(tmp_path):
    mp = make_run(tmp_path)
    t = mp.parent / "traces" / "n01_colleague_promise.json"
    t.write_text(t.read_text(encoding="utf-8").replace("O-1001", "O-1002"), encoding="utf-8")
    assert any("n01_colleague_promise" in p for p in recheck(mp))
    assert main([str(mp)]) == 1


def test_tampered_results_and_inputs_are_detected(tmp_path):
    mp = make_run(tmp_path)
    r = mp.parent / "results.jsonl"
    r.write_text(r.read_text(encoding="utf-8").replace('"failed": true', '"failed": false'), encoding="utf-8")
    assert any("results.jsonl" in p for p in recheck(mp))
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["files"]["agent/prompts/v1.txt"] = "0" * 64
    mp.write_text(json.dumps(m), encoding="utf-8")
    assert any("v1.txt" in p for p in recheck(mp))
