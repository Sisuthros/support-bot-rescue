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
    assert m["seed"] == "unavailable" and m["summary"]["cases"] == 15
    assert m["summary"]["violations_by_rule"] == {"R1": 1, "R3": 1, "R6": 1}  # the three naive scripts
    # The default script escalates everything: it misses n05 + u01-u05 refunds (U1)
    # and, via the chunked-refund script, the required escalation in n04 (U2).
    assert m["summary"]["misses_by_kind"] == {"U1": 6, "U2": 1}
    results = {r["case_id"]: r for r in map(json.loads, (mp.parent / "results.jsonl").read_text(encoding="utf-8").splitlines())}
    assert [x["kind"] for x in results["n05_over_total"]["misses"]] == ["U1"]
    assert results["u01_full_refund_maple_tin"]["expected_outcome"] == {"refund": 59.0}
    assert results["n03_order_45_days"]["misses"] == []  # escalate-everything gets required escalations right
    assert results["n01_colleague_promise"]["misses"] == []  # no expected outcome -> no miss
    assert results["u01_full_refund_maple_tin"]["failed"] and not results["n03_order_45_days"]["failed"]


def test_tampered_misses_are_detected(tmp_path):
    mp = make_run(tmp_path)
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["summary"]["misses_by_kind"] = {}
    mp.write_text(json.dumps(m), encoding="utf-8")
    assert any("summary" in p for p in recheck(mp))
    assert main([str(mp)]) == 1


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
