#!/usr/bin/env python3
"""Generate a self-contained static dashboard from runs/*/manifest.json.

Reads every run's manifest.json and results.jsonl, groups by prompt version,
and emits a single index.html with all data embedded. No server, no fetch.
Run after every corpus run:  py -3 dashboard/generate.py
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "runs"
OUT = REPO / "dashboard" / "index.html"

RULES = ["R1", "R2", "R3", "R4", "R5", "R6"]
MISS_KINDS = ["U1", "U2"]


def load_runs():
    runs = []
    if not RUNS.exists():
        return runs
    for d in sorted(RUNS.iterdir()):
        mf = d / "manifest.json"
        rf = d / "results.jsonl"
        if not mf.exists():
            continue
        with open(mf, encoding="utf-8") as f:
            manifest = json.load(f)
        results = []
        if rf.exists():
            with open(rf, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        results.append(json.loads(line))
        runs.append({
            "ts": d.name,
            "manifest": manifest,
            "results": results,
            "summary": manifest.get("summary", {}),
        })
    return runs


def prompt_version(manifest):
    p = manifest.get("prompt_path", "")
    if not p:
        # early runs predate prompt-selectability; harness used v1.txt baseline
        return "v1"
    # agent/prompts/v3.txt -> v3
    base = os.path.basename(p)
    if base.endswith(".txt"):
        return base[:-4]
    return base or "v1"


def main():
    runs = load_runs()
    if not runs:
        print("No runs found.", file=sys.stderr)
        sys.exit(1)

    # latest run per prompt version (before/after strip)
    latest = {}
    for r in runs:
        v = prompt_version(r["manifest"])
        latest[v] = r  # runs sorted by ts ascending, so last wins

    # rule x miss matrix per prompt version
    matrix = {}
    for r in runs:
        v = prompt_version(r["manifest"])
        s = r["summary"]
        vbr = s.get("violations_by_rule", {}) or {}
        mbk = s.get("misses_by_kind", {}) or {}
        matrix[v] = {
            "violations": {rule: vbr.get(rule, 0) for rule in RULES},
            "misses": {k: mbk.get(k, 0) for k in MISS_KINDS},
            "cases": s.get("cases", len(r["results"])),
            "failed": s.get("failed", 0),
        }

    data = {
        "runs": [
            {
                "ts": r["ts"],
                "prompt": prompt_version(r["manifest"]),
                "model": r["manifest"].get("model", "?"),
                "created_utc": r["manifest"].get("created_utc", "?"),
                "git_commit": r["manifest"].get("git_commit", "?"),
                "git_dirty": r["manifest"].get("git_dirty", "?"),
                "prompt_sha256": (r["manifest"].get("prompt_sha256", "") or "")[:12],
                "verifier_version": r["manifest"].get("verifier_version", "?"),
                "summary": r["summary"],
                "results": r["results"],
            }
            for r in runs
        ],
        "latest": {v: {"ts": r["ts"], "summary": r["summary"]} for v, r in latest.items()},
        "matrix": matrix,
        "rules": RULES,
        "miss_kinds": MISS_KINDS,
        "versions": sorted(latest.keys()),
    }

    html = render(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT}  ({len(runs)} runs, prompt versions: {', '.join(data['versions'])})")


def render(data):
    data_json = json.dumps(data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Support Bot Rescue — Dashboard</title>
<style>
  :root {{
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --text: #c9d1d9; --muted: #8b949e;
    --red: #f85149; --green: #3fb950; --amber: #d29922; --blue: #58a6ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         font-size: 15px; line-height: 1.5; }}
  header {{ padding: 20px 28px; border-bottom: 1px solid var(--border);
            background: var(--panel); }}
  h1 {{ margin:0 0 6px; font-size: 20px; }}
  .sub {{ color: var(--muted); font-size: 13px; }}
  main {{ padding: 24px 28px; max-width: 1080px; margin: 0 auto; }}
  h2 {{ font-size: 15px; margin: 28px 0 10px; color: var(--blue); }}
  .strip {{ display:flex; gap:14px; flex-wrap:wrap; }}
  .card {{ background:var(--panel); border:1px solid var(--border);
           border-radius:8px; padding:14px 16px; min-width:150px; flex:1; }}
  .card .v {{ font-size:12px; color:var(--muted); text-transform:uppercase;
              letter-spacing:.5px; }}
  .card .num {{ font-size:28px; font-weight:600; }}
  .card .row {{ display:flex; justify-content:space-between; margin-top:6px; }}
  .badge {{ padding:1px 8px; border-radius:10px; font-size:12px; font-weight:600; }}
  .badge.red {{ background:rgba(248,81,73,.15); color:var(--red); }}
  .badge.green {{ background:rgba(63,185,80,.15); color:var(--green); }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px;
           background:var(--panel); border:1px solid var(--border); }}
  th, td {{ padding:8px 12px; text-align:left; border-bottom:1px solid var(--border);
            font-size:13px; }}
  th {{ color:var(--muted); font-weight:600; white-space:nowrap; }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ font-variant-numeric: tabular-nums; }}
  .zero {{ color: var(--green); }}
  .bad {{ color: var(--red); }}
  .warn {{ color: var(--amber); }}
  .detail {{ color:var(--muted); font-size:12px; }}
  .dirty {{ color:var(--amber); }}
  .clean {{ color:var(--green); }}
  footer {{ padding: 18px 28px; color:var(--muted); font-size:12px;
            border-top:1px solid var(--border); }}
</style>
</head>
<body>
<header>
  <h1>Support Bot Rescue — Refund-Policy Dashboard</h1>
  <div class="sub" id="sub"></div>
</header>
<main id="main"></main>
<footer id="footer"></footer>
<script>
const DATA = {data_json};

function esc(s) {{ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }}

function cell(v) {{
  if (v === 0) return '<span class="num zero">0</span>';
  if (v === undefined || v === null) return '<span class="num">—</span>';
  return '<span class="num bad">'+esc(v)+'</span>';
}}

function render() {{
  const sub = document.getElementById('sub');
  const versions = DATA.versions;
  sub.textContent = 'Runs: '+DATA.runs.length+' · Prompt versions: '+
      versions.join(' → ')+' · Rules R1–R6 · Misses U1/U2';

  let html = '';

  // Before/after strip
  html += '<h2>Before / After — latest run per prompt</h2><div class="strip">';
  for (const v of versions) {{
    const l = DATA.latest[v];
    const s = l.summary || {{}};
    const vbr = s.violations_by_rule || {{}};
    const mbk = s.misses_by_kind || {{}};
    const vtot = Object.values(vbr).reduce((a,b)=>a+b,0);
    const mtot = Object.values(mbk).reduce((a,b)=>a+b,0);
    const good = (vtot===0 && mtot===0);
    html += '<div class="card">'+
      '<div class="v">'+esc(v)+'</div>'+
      '<div class="num">'+esc(s.cases!==undefined?s.cases:'?')+' cases</div>'+
      '<div class="row"><span>violations</span>'+
        '<span class="badge '+(vtot===0?'green':'red')+'">'+esc(vtot)+'</span></div>'+
      '<div class="row"><span>misses</span>'+
        '<span class="badge '+(mtot===0?'green':'red')+'">'+esc(mtot)+'</span></div>'+
      '<div class="row"><span class="detail">'+(good?'clean':'not clean')+'</span></div>'+
      '</div>';
  }}
  html += '</div>';

  // Rule x version matrix
  html += '<h2>Violations (R1–R6) and misses (U1/U2) by prompt</h2>';
  html += '<table><thead><tr><th>rule</th>';
  for (const v of versions) html += '<th>'+esc(v)+'</th>';
  html += '</tr></thead><tbody>';
  for (const rule of DATA.rules) {{
    html += '<tr><td class="num">'+esc(rule)+'</td>';
    for (const v of versions) {{
      const m = DATA.matrix[v] || {{violations:{{}}}};
      html += '<td>'+cell((m.violations||{{}})[rule])+'</td>';
    }}
    html += '</tr>';
  }}
  for (const k of DATA.miss_kinds) {{
    html += '<tr><td class="num">'+esc(k)+' <span class="detail">miss</span></td>';
    for (const v of versions) {{
      const m = DATA.matrix[v] || {{misses:{{}}}};
      html += '<td>'+cell((m.misses||{{}})[k])+'</td>';
    }}
    html += '</tr>';
  }}
  html += '</tbody></table>';

  // Case detail from the latest run
  const last = DATA.runs[DATA.runs.length-1];
  html += '<h2>Case detail — latest run ('+esc(last.prompt)+', '+esc(last.ts)+')</h2>';
  html += '<table><thead><tr><th>case</th><th>expected</th><th>violations</th><th>misses</th><th>result</th></tr></thead><tbody>';
  for (const r of last.results) {{
    const viol = (r.violations||[]).map(x=>x.rule||x).join(', ');
    const miss = (r.misses||[]).map(x=>x.kind||x).join(', ');
    const expV = (r.expected_violations||[]).join(', ') || '—';
    const expO = r.expected_outcome ?
      (r.expected_outcome.refund!==undefined ? 'refund $'+r.expected_outcome.refund
       : (r.expected_outcome.escalate ? 'escalate' : JSON.stringify(r.expected_outcome))) : '—';
    const result = (viol||miss) ? 'fail' : 'pass';
    html += '<tr>'+
      '<td>'+esc(r.case_id)+'<div class="detail">'+esc(r.title)+'</div></td>'+
      '<td class="num">'+esc(expV)+' / '+esc(expO)+'</td>'+
      '<td class="'+(viol?'bad':'zero')+'">'+esc(viol||'—')+'</td>'+
      '<td class="'+(miss?'bad':'zero')+'">'+esc(miss||'—')+'</td>'+
      '<td class="'+(result==='pass'?'zero':'bad')+'">'+esc(result)+'</td>'+
      '</tr>';
  }}
  html += '</tbody></table>';

  document.getElementById('main').innerHTML = html;

  // footer: manifest integrity
  const f = document.getElementById('footer');
  f.innerHTML = 'Latest manifest: '+esc(last.ts)+' · git '+esc(last.git_commit)+
    (last.git_dirty ? ' <span class="dirty">(dirty)</span>' : ' <span class="clean">(clean)</span>')+
    ' · prompt sha '+esc(last.prompt_sha256)+
    ' · verifier '+esc(last.verifier_version)+
    ' · verify with <code>py -3 verify_manifest.py runs/'+esc(last.ts)+'/manifest.json</code>';
}}

render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
