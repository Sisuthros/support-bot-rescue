import hashlib
import json

from verify_manifest import ROOT


def test_holdout_useful_file_matches_recorded_hash():
    actual = hashlib.sha256((ROOT / "corpus" / "holdout_useful.jsonl").read_bytes()).hexdigest()
    recorded = (ROOT / "corpus" / "HOLDOUT_USEFUL.sha256").read_text(encoding="utf-8").split()[0]
    assert actual == recorded, "holdout_useful.jsonl changed: update corpus/HOLDOUT_USEFUL.sha256 on purpose, not by accident"


def test_holdout_useful_is_separate_from_named_and_holdout():
    ids = lambda f: {json.loads(l)["id"] for l in (ROOT / "corpus" / f).read_text(encoding="utf-8").splitlines() if l.strip()}
    useful = ids("holdout_useful.jsonl")
    assert useful == {f"k{i:02d}" for i in range(1, 7)}
    assert not useful & ids("named.jsonl")
    assert not useful & ids("holdout.jsonl")


def test_holdout_useful_cases_expect_no_violations_and_an_outcome():
    cases = [json.loads(l) for l in (ROOT / "corpus" / "holdout_useful.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(cases) == 6
    assert all(c["expected_violations"] == [] and c.get("expected_outcome") for c in cases)
    assert sum("refund" in c["expected_outcome"] for c in cases) == 4
    assert sum(c["expected_outcome"].get("escalate") is True for c in cases) == 2
