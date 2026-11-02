import json
from pathlib import Path
from types import SimpleNamespace
from compiler import compile_policy

FIXTURE = Path(__file__).parent / "fixtures" / "maple.spec.json"

class FakeClient:
    def __init__(self, texts):
        self.texts = list(texts); self.requests = []
        self.responses = SimpleNamespace(create=self._create)
    def _create(self, **kwargs):
        self.requests.append(kwargs)
        text = self.texts.pop(0)
        return SimpleNamespace(id=f"resp-{len(self.requests)}", model="muse-wonder-1.0",
                               output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])])

def test_compile_retries_once_on_invalid_and_writes_artifacts(tmp_path):
    good = Path(FIXTURE).read_text(encoding="utf-8")
    client = FakeClient(["not json", good])
    out = tmp_path / "maple.spec.json"
    result = compile_policy.compile_policy_text(
        (Path(__file__).resolve().parent.parent / "maple" / "policy.md").read_text(encoding="utf-8"),
        client=client, model="muse-wonder-1.0", out_path=out, policy_sha256="abc123")
    assert len(client.requests) == 2
    assert result["provenance"]["response_id"] == "resp-2"
    assert result["provenance"]["model"] == "muse-wonder-1.0"
    written = json.loads(out.read_text(encoding="utf-8"))
    assert [r["id"] for r in written["rules"]] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    md = (tmp_path / "maple.spec.md").read_text(encoding="utf-8")
    assert "C1" in md and "A refund requires a successful" in md

def test_compile_gives_up_after_one_retry(tmp_path):
    client = FakeClient(["nope", "still nope"])
    try:
        compile_policy.compile_policy_text("policy", client=client, model="muse-wonder-1.0", out_path=tmp_path / "x.json", policy_sha256="x")
        assert False, "expected failure"
    except Exception:
        pass
    assert len(client.requests) == 2

