import copy, hashlib, json, threading
from types import SimpleNamespace
import pytest
from rescue import rescue_run
from rescue.live_view import LiveView
from test_rescue_run import FakeClient, SPEC, _msg, _tiny_store

def _world_payload():
    customers=[
      {"customer_id":"TC-01","name":"A Test","email":"a@example.com","payout_email":"pa@example.com","shipping_address":"1 Test Lane"},
      {"customer_id":"TC-02","name":"B Test","email":"b@example.com","payout_email":"pb@example.com","shipping_address":"2 Test Lane"}]
    orders=[]
    for i in range(10):
        orders.append({"order_id":f"T-{1001+i}","customer_id":"TC-01" if i%2==0 else "TC-02","items":["Fleece"],"total":40.0+i,"status":"delivered","delivered_on":"2026-10-30","internal_note":f"WAREHOUSE secret {i}"})
    return {"today":"2026-11-02","customers":customers,"orders":orders}

class WorldClient(FakeClient):
    def __init__(self): super().__init__(); self.world_calls=0
    def _create(self, **kwargs):
        if "WORLD GENERATION" in str(kwargs.get("input","")):
            self.requests.append(kwargs); self.world_calls+=1
            resp=_msg(json.dumps(_world_payload())); resp.id="world-1"; resp.model=kwargs.get("model"); return resp
        return super()._create(**kwargs)

class InexpressibleClient(FakeClient):
    def _create(self, **kwargs):
        if str(kwargs.get("input","")).startswith("You compile"):
            self.requests.append(kwargs)
            spec=copy.deepcopy(SPEC); spec["rules"].append({"id":"C7","primitive":"must_apologise_in_verse","quote":"The bot must apologise in verse whenever a customer is upset.","params":{}})
            resp=_msg(json.dumps(spec)); resp.id="compile-1"; resp.model=kwargs.get("model"); return resp
        return super()._create(**kwargs)

class SealCapturingClient(FakeClient):
    def __init__(self, out_root): super().__init__(); self.out_root=out_root; self.live_at_fix=None
    def _create(self, **kwargs):
        if "You are fixing the system prompt" in str(kwargs.get("input","")):
            pages=list(self.out_root.glob("*/live.html")); self.live_at_fix=pages[0].read_text(encoding="utf-8") if pages else ""
        return super()._create(**kwargs)

def test_concurrent_counts_match_sequential(tmp_path):
    stores=_tiny_store(tmp_path)
    seq=rescue_run.run_rescue(store="tiny",budget=100,out_root=tmp_path/"seq",client=FakeClient(),cases_count=2,holdout_count=1,stores_root=stores,workers=1)
    par=rescue_run.run_rescue(store="tiny",budget=100,out_root=tmp_path/"par",client=FakeClient(),cases_count=2,holdout_count=1,stores_root=stores,workers=4)
    s=json.loads((seq/"report.json").read_text()); p=json.loads((par/"report.json").read_text())
    assert p["counts"]==s["counts"]
    for g in ("v1_cases","v2_cases","v1_holdout","v2_holdout"):
        assert (par/"results"/f"{g}.jsonl").read_text()==(seq/"results"/f"{g}.jsonl").read_text()

def test_budget_never_exceeded_under_concurrency():
    class Inner:
        def __init__(self): self.calls=0; self.lock=threading.Lock(); self.responses=SimpleNamespace(create=self._c)
        def _c(self, **kw):
            with self.lock: self.calls+=1
            return _msg("ok")
    inner=Inner(); counted=rescue_run.CountingClient(inner, budget=5); errors=[]
    def attempt():
        try: counted.responses.create(model="x", input="y")
        except RuntimeError as e: errors.append(str(e))
    threads=[threading.Thread(target=attempt) for _ in range(20)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert inner.calls==5 and counted.calls==5 and len(errors)==15

def test_policy_file_without_world_generates_once(tmp_path):
    policy=tmp_path/"policy.md"; policy.write_text("# Tiny Outfitters support policy (fictional)\n\n"+"\n\n".join(__import__("test_rescue_run").SENTENCES.values())+"\n",encoding="utf-8")
    client=WorldClient(); run=rescue_run.run_rescue(policy_file=policy,budget=100,out_root=tmp_path/"runs",client=client,cases_count=2,holdout_count=1,workers=2)
    assert client.world_calls==1
    world=json.loads((run/"world.json").read_text()); assert len(world["orders"])==10
    assert "generated" in (run/"run.log").read_text()
    report=json.loads((run/"report.json").read_text()); assert report["world_generated"] is True

def test_inexpressible_rule_surfaces_and_run_continues(tmp_path):
    stores=_tiny_store(tmp_path); p=stores/"tiny"/"policy.md"; p.write_text(p.read_text()+"\nThe bot must apologise in verse whenever a customer is upset.\n",encoding="utf-8")
    run=rescue_run.run_rescue(store="tiny",budget=100,out_root=tmp_path/"runs",client=InexpressibleClient(),cases_count=2,holdout_count=1,stores_root=stores,workers=2)
    report=json.loads((run/"report.json").read_text())
    assert any(x.startswith("not expressible yet:") and "apologise in verse" in x for x in report["not_expressible"])
    assert "not expressible yet:" in (run/"live.html").read_text()
    assert report["counts"]["v2_cases"]["cases"]==2

def test_live_html_written_and_seal_present_before_fix(tmp_path):
    stores=_tiny_store(tmp_path); out=tmp_path/"runs"; client=SealCapturingClient(out)
    run=rescue_run.run_rescue(store="tiny",budget=100,out_root=out,client=client,cases_count=2,holdout_count=1,stores_root=stores,workers=3)
    sha=(run/"holdout.sha256").read_text().strip()
    assert client.live_at_fix and sha in client.live_at_fix
    html=(run/"live.html").read_text(); assert 'http-equiv="refresh"' in html and sha in html and "all counts match" in html
    for stage in ("v1_cases","v2_cases","v1_holdout","v2_holdout"): assert stage in html

def test_cli_help_shows_live_aliases(capsys):
    with pytest.raises(SystemExit) as e: rescue_run.main(["--help"])
    assert e.value.code==0; out=capsys.readouterr().out; assert "--cases" in out and "--holdout" in out and "--workers" in out and "--policy-file" in out
