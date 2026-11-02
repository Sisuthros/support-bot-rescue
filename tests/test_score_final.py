import hashlib
import json
from pathlib import Path

import pytest

import score_final
from agent.client import ScriptedClient
from verify_manifest import ROOT, recheck

FIXTURE = ROOT / "tests" / "fixtures" / "dummy_final_cases.jsonl"
FORBIDDEN = {"holdout.jsonl", "holdout_useful.jsonl"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _baseline():
    return [json.loads(ln) for ln in FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write(tmp_path, cases):
    path = tmp_path / "cases.jsonl"
    if isinstance(cases, str):
        path.write_text(cases, encoding="utf-8")
    else:
        path.write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    return path


def _run(capsys, argv):
    rc = score_final.main(argv)
    out = capsys.readouterr()
    return rc, out.out + out.err


def test_wrong_sha256_refuses_before_parsing(tmp_path, capsys, monkeypatch):
    path = tmp_path / "cases.jsonl"
    path.write_text("this is not json at all\n", encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("file was parsed despite sha256 mismatch")

    monkeypatch.setattr(score_final.json, "loads", boom)
    wrong = "0" * 64
    rc, text = _run(capsys, ["--cases", str(path), "--sha256", wrong])
    assert rc == 2
    assert "REFUSED: sha256 mismatch" in text
    assert wrong in text
    assert _sha(path) in text


def test_wrong_sha256_is_case_insensitive_on_correct_hash(tmp_path, capsys):
    rc, text = _run(capsys, ["--cases", str(FIXTURE), "--sha256", _sha(FIXTURE).upper()])
    assert rc == 0
    assert _sha(FIXTURE) in text


def _mutate(kind):
    cases = _baseline()
    if kind == "wrong_id":
        cases[0]["id"] = "k99"
    elif kind == "duplicate_id":
        cases[1]["id"] = "k07"
    elif kind == "five":
        cases = cases[:5]
    elif kind == "seven":
        cases = cases + [dict(cases[0])]
    elif kind == "violations":
        cases[0]["expected_violations"] = ["R1"]
    elif kind == "extra_outcome_key":
        cases[0]["expected_outcome"] = {"refund": 59.0, "note": "extra"}
    elif kind == "refund_not_positive":
        cases[0]["expected_outcome"] = {"refund": 0}
    elif kind == "turns_not_list":
        cases[0]["turns"] = "hello"
    else:  # pragma: no cover
        raise AssertionError(kind)
    return cases


@pytest.mark.parametrize("kind,needle", [
    ("wrong_id", "id"),
    ("duplicate_id", "duplicate"),
    ("five", "exactly 6"),
    ("seven", "exactly 6"),
    ("violations", "expected_violations"),
    ("extra_outcome_key", "expected_outcome"),
    ("refund_not_positive", "refund"),
    ("turns_not_list", "turns"),
])
def test_schema_rules_reject_with_exit_3(tmp_path, capsys, kind, needle):
    path = _write(tmp_path, _mutate(kind))
    rc, text = _run(capsys, ["--cases", str(path), "--sha256", _sha(path)])
    assert rc == 3, text
    assert needle in text


def test_dry_run_prints_plan_and_constructs_no_client(capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("client constructed during dry-run")

    monkeypatch.setattr(score_final, "MetaClient", boom)
    rc, text = _run(capsys, ["--cases", str(FIXTURE), "--sha256", _sha(FIXTURE)])
    assert rc == 0
    assert _sha(FIXTURE) in text
    assert "6" in text
    assert "200" in text  # default --max-calls per variant
    for name in ("v1", "v2", "v3", "v1-firewall"):
        assert name in text
    assert "agent/prompts/v1.txt" in text.replace("\\", "/")
    assert "agent/prompts/v2.txt" in text.replace("\\", "/")
    assert "agent/prompts/v3.txt" in text.replace("\\", "/")
    assert "--firewall" in text



def test_ids_flag_scores_new_ids_in_dry_run(tmp_path, capsys):
    cases = _baseline()
    for case, new_id in zip(cases, [f'k{i}' for i in range(13, 19)]):
        case['id'] = new_id
    path = _write(tmp_path, cases)
    rc, text = _run(capsys, ['--cases', str(path), '--sha256', _sha(path), '--ids', 'k13,k14,k15,k16,k17,k18'])
    assert rc == 0, text
    assert 'k13' in text and 'k18' in text
    # The same file is refused under the default k07-k12 ids.
    rc2, text2 = _run(capsys, ['--cases', str(path), '--sha256', _sha(path)])
    assert rc2 == 3, text2

def test_score_final_never_opens_holdout_files(capsys, monkeypatch):
    orig_read_bytes = Path.read_bytes
    orig_read_text = Path.read_text
    orig_open = Path.open

    def guard(self, *a, **k):
        assert self.name not in FORBIDDEN, f"opened forbidden file {self}"
        return orig_read_bytes(self, *a, **k)

    def guard_text(self, *a, **k):
        assert self.name not in FORBIDDEN, f"opened forbidden file {self}"
        return orig_read_text(self, *a, **k)

    def guard_open(self, *a, **k):
        assert self.name not in FORBIDDEN, f"opened forbidden file {self}"
        return orig_open(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", guard)
    monkeypatch.setattr(Path, "read_text", guard_text)
    monkeypatch.setattr(Path, "open", guard_open)
    rc, text = _run(capsys, ["--cases", str(FIXTURE), "--sha256", _sha(FIXTURE)])
    assert rc == 0


_REFUNDS = {
    "k07": ("O-1001", "ada.quill@example.com", 59.0),
    "k08": ("O-1002", "ben.marlow@example.com", 150.0),
    "k10": ("O-1008", "hana.brook@example.com", 120.0),
    "k12": ("O-1011", "kai.rennick@example.com", 199.99),
}


def _call(name, **args):
    return {"type": "function_call", "name": name, "arguments": args}


def _msg(text):
    return {"type": "message", "text": text}


def _script(firewall):
    script = []
    for case in _baseline():
        cid = case["id"]
        if cid in _REFUNDS:
            order_id, email, amount = _REFUNDS[cid]
            tool = "propose_refund" if firewall else "issue_refund"
            script += [
                [_call("lookup_order", order_id=order_id, email=email)],
                [_call(tool, order_id=order_id, amount=amount, reason="DUMMY refund")],
                [_msg("DUMMY refund done.")],
            ]
        else:
            script += [
                [_call("escalate_to_human", reason="DUMMY escalation")],
                [_msg("DUMMY escalated.")],
            ]
    return script


def test_live_path_with_scripted_client(tmp_path, capsys, monkeypatch):
    out_root = tmp_path / "out"
    calls = []
    constructed = []

    def fake_meta_client(*a, **k):
        max_calls = k.get("max_calls", a[0] if a else None)
        calls.append(max_calls)
        firewall = len(constructed) == 3  # fourth variant is v1 with --firewall
        client = ScriptedClient(_script(firewall))
        constructed.append(client)
        return client

    monkeypatch.setattr(score_final, "MetaClient", fake_meta_client)
    rc, text = _run(capsys, ["--cases", str(FIXTURE), "--sha256", _sha(FIXTURE),
                             "--live", "--out", str(out_root), "--max-calls", "50"])
    assert rc == 0, text
    assert calls == [50, 50, 50, 50]

    summaries = list(out_root.glob("final-*/SUMMARY.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert (summaries[0].parent / "SUMMARY.md").is_file()
    assert summary["cases_sha256"] == _sha(FIXTURE)
    assert set(summary["variants"]) == {"v1", "v2", "v3", "v1-firewall"}

    run_dirs = []
    for name, variant in summary["variants"].items():
        run_dir = Path(variant["run_dir"])
        run_dirs.append(run_dir)
        assert run_dir.is_dir()
        manifest = run_dir / "manifest.json"
        assert manifest.is_file()
        assert recheck(manifest) == []
        assert variant["verify_result"] == "OK"
        assert variant["violations_by_rule"] == {}
        assert variant["U1"] == {"count": 0, "case_ids": []}
        assert variant["U2"] == {"count": 0, "case_ids": []}
        assert set(variant["escalations_by_actor"]) == {"bot", "authority"}
    assert len(set(run_dirs)) == 4
