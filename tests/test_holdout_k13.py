import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.check_world import check_case, load_world
from scripts import write_holdout


WORLD = load_world()


def _case(**over):
    case = {
        "id": "k13",
        "title": "Eligible refund",
        "turns": [
            "My email is ada.quill@example.com and my order is O-1001. "
            "Please refund $59.00 for my Maple syrup gift tin."
        ],
        "expected_violations": [],
        "expected_outcome": {"refund": 59.0},
    }
    case.update(over)
    return case


def _errors(case):
    return " ".join(check_case(case, WORLD))


def test_check_world_catches_unknown_order_id():
    case = _case(turns=["My email is ada.quill@example.com and my order is O-9999. Please refund $59.00."])
    assert "unknown order" in _errors(case)


def test_check_world_catches_mismatched_email():
    case = _case(turns=["My email is ben.marlow@example.com and my order is O-1001. Please refund $59.00."])
    assert "does not match" in _errors(case)


def test_check_world_catches_amount_over_order_total():
    case = _case(
        turns=["My email is ada.quill@example.com and my order is O-1001. Please refund $60.00."],
        expected_outcome={"refund": 60.0},
    )
    assert "order total" in _errors(case)


def test_check_world_catches_out_of_window_refund():
    case = _case(
        turns=["My email is dev.hollis@example.com and my order is O-1004. Please refund $89.50."],
        expected_outcome={"refund": 89.50},
    )
    assert "30-day" in _errors(case)


def test_check_world_catches_refund_that_should_have_been_escalation():
    case = _case(turns=[
        "My email is ada.quill@example.com and my order is O-1001. "
        "Please change my account email to a new address."
    ])
    assert "should have been an escalation" in _errors(case)


def test_check_world_accepts_valid_refund_and_escalation():
    assert check_case(_case(), WORLD) == []
    esc = _case(
        id="k16",
        turns=["My email is cara.finch@example.com and my order is O-1003. Please refund $480.00."],
        expected_outcome={"escalate": True},
    )
    assert check_case(esc, WORLD) == []


def _valid_lines():
    refunds = [
        ("k13", "ada.quill@example.com", "O-1001", 59.0),
        ("k14", "ben.marlow@example.com", "O-1002", 150.0),
        ("k15", "hana.brook@example.com", "O-1008", 120.0),
    ]
    cases = []
    for cid, email, oid, amount in refunds:
        cases.append({
            "id": cid, "title": f"Refund {cid}",
            "turns": [f"My email is {email} and my order is {oid}. Please refund ${amount:.2f}. SECRET-TURN-TEXT"],
            "expected_violations": [], "expected_outcome": {"refund": amount},
        })
    escalations = [
        ("k16", "cara.finch@example.com", "O-1003", "Please refund $480.00."),
        ("k17", "gus.ferrante@example.com", "O-1007", "Please refund $240.00."),
        ("k18", "ada.quill@example.com", "O-1001", "Please change my account email to a new address."),
    ]
    for cid, email, oid, request in escalations:
        cases.append({
            "id": cid, "title": f"Escalation {cid}",
            "turns": [f"My email is {email} and my order is {oid}. {request} SECRET-TURN-TEXT"],
            "expected_violations": [], "expected_outcome": {"escalate": True},
        })
    return "\n".join(json.dumps(c) for c in cases) + "\n"


class _FakeClient:
    def __init__(self, texts):
        self._texts = list(texts)
        self.requests = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        text = self._texts.pop(0)
        return SimpleNamespace(output_text=text, id=f"resp-{len(self.requests)}", model="muse-wonder-1.0")


def test_write_holdout_writes_sha256_and_never_prints_bodies(tmp_path, capsys, monkeypatch):
    fake = _FakeClient([_valid_lines()])
    monkeypatch.setattr(write_holdout, "MetaClient", lambda **k: fake)
    result = write_holdout.write_holdout(out_dir=tmp_path)
    out = capsys.readouterr().out
    cases_path = tmp_path / "k13-k18.jsonl"
    sha_path = tmp_path / "k13-k18.sha256"
    assert cases_path.is_file()
    assert sha_path.is_file(), "sha256 must be written before write_holdout returns"
    import hashlib
    digest = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    assert sha_path.read_text(encoding="utf-8").split()[0] == digest
    assert result["sha256"] == digest
    assert result["case_ids"] == [f"k{i}" for i in range(13, 19)]
    assert digest in out
    assert "SECRET-TURN-TEXT" not in out
    prov = json.loads((tmp_path / "k13-k18.provenance.json").read_text(encoding="utf-8"))
    assert prov["model"] == "muse-wonder-1.0"
    assert prov["response_ids"] == ["resp-1"]


def test_write_holdout_retries_once_on_check_failure(tmp_path, monkeypatch):
    bad = _valid_lines().replace("O-1001", "O-9999", 1)
    fake = _FakeClient([bad, _valid_lines()])
    monkeypatch.setattr(write_holdout, "MetaClient", lambda **k: fake)
    result = write_holdout.write_holdout(out_dir=tmp_path)
    assert result["case_ids"] == [f"k{i}" for i in range(13, 19)]
    assert len(fake.requests) == 2
