import hashlib
import json

from verify_manifest import ROOT


def test_holdout_file_matches_recorded_hash():
    actual = hashlib.sha256((ROOT / "corpus" / "holdout.jsonl").read_bytes()).hexdigest()
    recorded = (ROOT / "corpus" / "HOLDOUT.sha256").read_text(encoding="utf-8").split()[0]
    assert actual == recorded, "holdout.jsonl changed: update corpus/HOLDOUT.sha256 on purpose, not by accident"


def test_holdout_is_separate_from_named():
    ids = lambda f: {json.loads(l)["id"] for l in (ROOT / "corpus" / f).read_text(encoding="utf-8").splitlines() if l.strip()}
    assert len(ids("holdout.jsonl")) == 5 and not ids("holdout.jsonl") & ids("named.jsonl")
