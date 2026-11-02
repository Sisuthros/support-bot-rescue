import json
from pathlib import Path
from compiler.agreement import run_agreement

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "maple.spec.json"

def test_agreement_on_checked_in_spec_offline(tmp_path):
    out = tmp_path / "agreement.json"
    report = run_agreement(FIXTURE, evidence_root=ROOT / "evidence" / "5423ab2", out_path=out)
    assert report["runs"] == 13
    assert report["total"] == 163
    assert report["agreement"] == 163
    assert report["disagreements"] == []
    assert json.loads(out.read_text(encoding="utf-8"))["total"] == 163
