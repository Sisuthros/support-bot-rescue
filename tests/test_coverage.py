import copy, json
from pathlib import Path
import pytest
from compiler.coverage import compute_coverage, split_sentences
from compiler.dsl import SpecError, validate_spec
from rescue import rescue_run
from test_rescue_run import FakeClient, SPEC, SENTENCES, _tiny_store

ROOT = Path(__file__).resolve().parent.parent
POLICY = (
    "# Tiny Outfitters support policy (fictional)\n\n"
    "Welcome to Tiny Outfitters.\n\n"
    "- " + SENTENCES["cap"] + "\n\n"
    "Customers with VIP status get free returns at any time.\n\n"
    "The shop sends a newsletter every month.\n"
)

def _spec_with_uncovered():
    spec = {"version": "1.0", "rules": [copy.deepcopy(SPEC["rules"][2])],
            "uncovered": [{"quote": "Customers with VIP status get free returns at any time.",
                           "reason": "no primitive expresses VIP status"}]}
    return spec

def test_validator_accepts_spec_with_and_without_uncovered():
    validate_spec(copy.deepcopy(SPEC), policy_text="\n".join(SENTENCES.values()))
    spec = validate_spec(_spec_with_uncovered(), policy_text=POLICY)
    assert spec.uncovered[0].quote.startswith("Customers with VIP")
    assert spec.uncovered[0].reason == "no primitive expresses VIP status"

def test_validator_rejects_non_verbatim_uncovered_quote():
    spec = _spec_with_uncovered(); spec["uncovered"][0]["quote"] = "VIP customers always win."
    with pytest.raises(SpecError, match="verbatim"):
        validate_spec(spec, policy_text=POLICY)
    spec = _spec_with_uncovered(); spec["uncovered"][0]["reason"] = "  "
    with pytest.raises(SpecError):
        validate_spec(spec, policy_text=POLICY)

def test_compiled_maple_spec_still_validates():
    data = json.loads((ROOT / "compiled" / "maple.spec.json").read_text(encoding="utf-8"))
    spec = validate_spec(data)
    assert len(spec.rules) == 6 and spec.uncovered == ()

def test_coverage_labels_all_three_kinds_and_skips_headings():
    cov = compute_coverage(POLICY, _spec_with_uncovered())
    by = {e["sentence"]: e["label"] for e in cov["sentences"]}
    assert by[SENTENCES["cap"]] == "enforced"
    assert by["Customers with VIP status get free returns at any time."] == "needs_review"
    assert by["The shop sends a newsletter every month."] == "not_addressed"
    assert by["Welcome to Tiny Outfitters."] == "not_addressed"
    assert not any("Tiny Outfitters support policy" in s for s in by)
    entry = next(e for e in cov["sentences"] if e["label"] == "needs_review")
    assert entry["reason"] == "no primitive expresses VIP status"
    assert cov["headline"] == "1 of 4 policy sentences are enforced by code; 1 need human review; 2 were not addressed by the compiler"

def test_split_sentences_bullets_count():
    assert SENTENCES["cap"] in split_sentences(POLICY)

class UncoveredClient(FakeClient):
    def _create(self, **kwargs):
        if str(kwargs.get("input", "")).startswith("You compile"):
            self.requests.append(kwargs)
            spec = copy.deepcopy(SPEC)
            spec["uncovered"] = [{"quote": "Customers with VIP status get free returns at any time.",
                                  "reason": "no primitive expresses VIP status or free returns"}]
            from test_rescue_run import _msg
            resp = _msg(json.dumps(spec)); resp.id = "compile-1"; resp.model = kwargs.get("model"); return resp
        return super()._create(**kwargs)

def _run_with_extra_sentence(tmp_path, client, extra):
    stores = _tiny_store(tmp_path); p = stores / "tiny" / "policy.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n" + extra + "\n", encoding="utf-8")
    return rescue_run.run_rescue(store="tiny", budget=100, out_root=tmp_path / "runs", client=client, cases_count=2, holdout_count=1, stores_root=stores, workers=2)

def test_scripted_run_left_out_sentence_is_not_addressed(tmp_path):
    run = _run_with_extra_sentence(tmp_path, FakeClient(), "The shop sends a newsletter every month.")
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    entry = next(e for e in report["coverage"]["sentences"] if e["sentence"] == "The shop sends a newsletter every month.")
    assert entry["label"] == "not_addressed"
    html = (run / "live.html").read_text(encoding="utf-8")
    assert report["coverage"]["headline"] in html and "compiler said nothing" in html
    assert report["coverage"]["headline"] in (run / "report.md").read_text(encoding="utf-8")
    assert report["coverage"]["headline"] in (run / "spec.md").read_text(encoding="utf-8")

def test_scripted_run_uncovered_entry_is_needs_review(tmp_path):
    run = _run_with_extra_sentence(tmp_path, UncoveredClient(), "Customers with VIP status get free returns at any time.")
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    entry = next(e for e in report["coverage"]["sentences"] if e["sentence"].startswith("Customers with VIP"))
    assert entry["label"] == "needs_review" and entry["reason"] == "no primitive expresses VIP status or free returns"
    html = (run / "live.html").read_text(encoding="utf-8")
    assert "needs human review: no primitive expresses VIP status or free returns" in html
