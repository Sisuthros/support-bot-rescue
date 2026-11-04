import json

from scripts import verify_claims


def test_every_check_passes_on_the_real_repo():
    assert verify_claims.CHECKS, "no checks registered"
    for claim_id, check in verify_claims.CHECKS.items():
        ok, message = check()
        assert ok, message
        assert message.startswith(f"{claim_id}:")


def test_c1_passes_in_a_clean_clone_without_the_sibling_worktree(monkeypatch, tmp_path):
    import demo

    monkeypatch.setattr(demo, "WORKTREE_VERIFIER", tmp_path / "no-worktree" / "verify_manifest.py")
    monkeypatch.setattr(verify_claims, "_manifest_cache", {})
    ok, message = verify_claims.check_c1()
    assert ok, message


def test_tampered_copy_fails(monkeypatch, tmp_path):
    report = json.loads(verify_claims.C24_REPORT_PATH.read_text(encoding="utf-8"))
    report["wall_seconds"] = report["wall_seconds"] + 1000
    tampered = tmp_path / "report.json"
    tampered.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(verify_claims, "C24_REPORT_PATH", tampered)
    ok, message = verify_claims.check_c24()
    assert ok is False
    assert message.startswith("C24:")


def test_only_filters(capsys):
    assert verify_claims.main(["--only", "C23,C30"]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert any(line.startswith("OK C23:") for line in lines)
    assert any(line.startswith("OK C30:") for line in lines)
    assert not any("C24" in line for line in lines)
    assert lines[-1] == "2 of 2 claims OK"


def test_skip_never_counts_as_ok(capsys):
    assert verify_claims.main(["--only", "C18"]) == 1
    out = capsys.readouterr().out
    assert "SKIP C18:" in out
    assert out.splitlines()[-1] == "0 of 0 claims OK"
