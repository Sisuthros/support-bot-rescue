"""Static live view for a Rescue Run: one self-contained HTML file, refreshed
by the browser every 2 seconds via meta refresh. No server, no external assets.
"""
from __future__ import annotations
import html, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGES = ("v1_cases", "fix", "v2_cases", "v1_holdout", "v2_holdout")
LABELS = {"v1_cases":"v1 cases","fix":"fix","v2_cases":"v2 cases","v1_holdout":"v1 holdout","v2_holdout":"v2 holdout"}

def _empty():
    return {"cases":0,"failed":0,"violations_by_rule":{},"misses_by_kind":{}}

class LiveView:
    def __init__(self, run_dir: Path | str, policy_text: str = "", store: str = "") -> None:
        self.run_dir = Path(run_dir); self.path = self.run_dir / "live.html"
        self.policy_text = policy_text; self.store = store
        self.stage = "starting"; self.rules: list[dict] = []; self.not_expressible: list[str] = []
        self.coverage: dict | None = None; self.uncovered: list[dict] = []
        self.seal_sha: str | None = None; self.sealed_at: str | None = None
        self.counts = {s: _empty() for s in STAGES}
        self.lines: list[str] = []; self.last_tool: str = "none yet"; self.last_verdict: str = ""
        self.rejudge_result: str | None = None; self.wall_seconds: Any = None
        self.write()
    def write(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(), encoding="utf-8")
    def set_stage(self, stage: str, line: str | None = None) -> None:
        self.stage = stage
        if line: self.add_line(line, write=False)
        self.write()
    def add_line(self, line: str, write: bool = True) -> None:
        self.lines.append(line); self.lines = self.lines[-30:]
        if write: self.write()
    def set_rules(self, rules: list[dict], not_expressible: list[str] | None = None, coverage: dict | None = None, uncovered: list[dict] | None = None) -> None:
        self.rules = list(rules)
        if not_expressible is not None: self.not_expressible = list(not_expressible)
        if uncovered is not None: self.uncovered = list(uncovered)
        if coverage is not None: self.coverage = coverage
        self.write()
    def set_coverage(self, coverage: dict | None, uncovered: list[dict] | None = None) -> None:
        self.coverage = coverage
        if uncovered is not None: self.uncovered = list(uncovered)
        self.write()
    def set_seal(self, sha: str) -> None:
        self.seal_sha = sha; self.sealed_at = datetime.now(timezone.utc).isoformat(timespec="seconds"); self.write()
    def add_result(self, group: str, result: dict, payload: dict | None = None) -> None:
        if group not in self.counts: return
        c = self.counts[group]; c["cases"] += 1
        if result.get("failed"): c["failed"] += 1
        for v in result.get("violations", []): c["violations_by_rule"][v["rule"]] = c["violations_by_rule"].get(v["rule"],0)+1
        for m in result.get("misses", []): c["misses_by_kind"][m["kind"]] = c["misses_by_kind"].get(m["kind"],0)+1
        trace = (payload or {}).get("trace") or []
        if trace:
            last = trace[-1]; self.last_tool = f"{last.get('name','?')} {json.dumps(last.get('args',{}), sort_keys=True)}"
        else: self.last_tool = "no tool call"
        if result.get("violations"): self.last_verdict = "violation " + ", ".join(sorted({v["rule"] for v in result["violations"]}))
        elif result.get("misses"): self.last_verdict = "miss " + ", ".join(sorted({m["kind"] for m in result["misses"]}))
        else: self.last_verdict = "ok"
        cls = "violation" if result.get("violations") else ("miss" if result.get("misses") else "ok")
        self.add_line(f"{group}/{result.get('case_id','?')}: last tool {self.last_tool} -> {self.last_verdict}", write=False)
        self.write()
    def set_fix(self, failing_count: int) -> None:
        self.counts["fix"] = {"cases": failing_count, "failed": failing_count, "violations_by_rule": {}, "misses_by_kind": {}}
        self.stage = "fix"; self.write()
    def finish(self, rejudge_result: str, wall_seconds: Any) -> None:
        self.rejudge_result = rejudge_result; self.wall_seconds = wall_seconds; self.stage = "done"; self.write()
    def _coverage(self) -> dict:
        if self.coverage is not None:
            return self.coverage
        try:
            from compiler.coverage import compute_coverage
            spec = {"rules": self.rules, "uncovered": self.uncovered}
            return compute_coverage(self.policy_text, spec)
        except Exception:
            return {"headline": "", "sentences": []}
    def _policy_html(self) -> str:
        text = html.escape(self.policy_text)
        cov = self._coverage() if self.policy_text else {"sentences": []}
        entries = cov.get("sentences") or []
        if entries:
            labelled = set()
            for entry in entries:
                q = html.escape(str(entry.get("sentence", "")))
                if not q or q not in text or q in labelled:
                    continue
                labelled.add(q)
                label = entry.get("label")
                if label == "enforced":
                    text = text.replace(q, f"<mark>{q}</mark>", 1)
                elif label == "needs_review":
                    reason = html.escape(str(entry.get("reason") or ""))
                    text = text.replace(q, f"<mark class='needs-review'>{q}</mark> <span class='needs-review'>needs human review: {reason}</span>", 1)
                else:
                    text = text.replace(q, f"<span class='not-addressed'>{q}</span> <span class='not-addressed'>compiler said nothing</span>", 1)
            return text
        for r in self.rules:
            q = html.escape(str(r.get("quote","")))
            if q and q in text: text = text.replace(q, f"<mark>{q}</mark>", 1)
        return text
    def render(self) -> str:
        e = html.escape
        rules = "".join(f"<tr><td>{e(str(r.get('id','')))}</td><td>{e(str(r.get('primitive','')))}</td><td><mark>{e(str(r.get('quote','')))}</mark></td></tr>" for r in self.rules) or "<tr><td colspan='3'>compiling...</td></tr>"
        notexp = "".join(f"<p class='violation'>{e(x)}</p>" for x in self.not_expressible)
        rows = ""
        for s in STAGES:
            c = self.counts[s]
            rows += (f"<tr class='{'current' if self.stage==s else ''}'><td>{LABELS[s]}</td><td>{c['cases']}</td>"
                     f"<td class='{'violation' if c['failed'] else ''}'>{c['failed']}</td>"
                     f"<td class='violation'>{e(json.dumps(c['violations_by_rule'], sort_keys=True))}</td>"
                     f"<td class='miss'>{e(json.dumps(c['misses_by_kind'], sort_keys=True))}</td></tr>")
        seal = (f"<p>sha256: <code>{e(self.seal_sha)}</code></p><p>sealed at: {e(self.sealed_at or '')}</p>" if self.seal_sha else "<p>not sealed yet</p>")
        final = ""
        if self.rejudge_result is not None:
            final = f"<h2>Final</h2><p>Rejudge: {e(self.rejudge_result)}</p><p>Wall-clock time: {e(str(self.wall_seconds))} seconds</p>"
        lines = "\n".join(self.lines[-20:])
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<title>Support Bot Rescue - live</title>
<style>
body{{background:#14161a;color:#e8e6e1;font-family:Georgia,'Times New Roman',serif;margin:2rem auto;max-width:980px;padding:0 1rem;line-height:1.5}}
h1,h2{{font-weight:normal}} code,pre,table{{font-family:Consolas,monospace;font-size:.9em}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid #333;padding:.35rem .5rem;text-align:left}}
mark{{background:#3a4a2f;color:#e8e6e1;padding:.05rem .15rem}} mark.needs-review,.needs-review{{background:#6b5016;color:#ffdf9e;padding:.05rem .15rem}} .not-addressed{{color:#9a9a9a;background:#26292f;padding:.05rem .15rem}} .violation{{color:#d98c8c}} .miss{{color:#e0b36a}} .ok{{color:#9fc49f}}
pre{{white-space:pre-wrap;background:#1c1f24;padding:1rem}} tr.current td{{background:#1f242c}}
</style></head><body>
<h1>Support Bot Rescue - live</h1>
<p>Store: {e(self.store)} &middot; Stage: {e(self.stage)}</p>
<h2>Policy and compiled rules</h2>
<p class='coverage-headline'>{e(str(self._coverage().get("headline","")))}</p>
<pre>{self._policy_html()}</pre>
<table><tr><th>rule</th><th>primitive</th><th>quoted policy sentence</th></tr>{rules}</table>
{notexp}
<h2>Holdout seal</h2>
{seal}
<h2>Stages</h2>
<table><tr><th>stage</th><th>cases</th><th>failed</th><th>violations by rule</th><th>misses by kind</th></tr>{rows}</table>
<h2>Latest traces</h2>
<p>Last tool call: <code>{e(self.last_tool)}</code> &middot; verdict: <span class="{'violation' if self.last_verdict.startswith('violation') else 'miss' if self.last_verdict.startswith('miss') else 'ok'}">{e(self.last_verdict)}</span></p>
<pre>{e(lines)}</pre>
{final}
</body></html>
"""
