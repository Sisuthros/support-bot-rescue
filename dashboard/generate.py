#!/usr/bin/env python3
"""Generate a self-contained static dashboard from runs/*/manifest.json.

Reads every run's manifest.json and results.jsonl, groups by
(corpus, prompt version, firewall), and emits a single index.html with
aggregated data embedded. Holdout corpora are classified from case ID prefix
(k* / h*) and shown only as aggregate counts — no case IDs, titles, or traces.

Usage: py -3 dashboard/generate.py [--commit SHA]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "runs"
OUT = REPO / "dashboard" / "index.html"

RULES = ["R1", "R2", "R3", "R4", "R5", "R6"]
MISS_KINDS = ["U1", "U2"]

# ── holdout classification (case ID prefix — NEVER read corpus file) ──
HOLDOUT_PREFIXES = {"h", "k"}


def is_holdout_run(run: dict) -> bool:
    results = run["results"]
    if not results:
        return False
    cid = results[0].get("case_id", "")
    return cid[:1] in HOLDOUT_PREFIXES


def corpus_label(run: dict) -> str:
    """Stable corpus label: corpus_path first, then case-id prefix fallback."""
    cp = run["manifest"].get("corpus_path", "") or ""
    if cp:
        return os.path.splitext(os.path.basename(cp))[0]
    results = run["results"]
    if not results:
        return "unknown"
    cid = results[0].get("case_id", "")
    prefix = cid[:1]
    return {
        "h": "holdout_attack",
        "k": "holdout_useful",
        "n": "named",
        "a": "attacks/wonder",
        "l": "attacks/live",
    }.get(prefix, "unknown")


def prompt_version(manifest: dict) -> str:
    p = manifest.get("prompt_path", "") or ""
    if not p:
        return "v1"
    base = os.path.basename(p)
    return base[:-4] if base.endswith(".txt") else (base or "v1")


def firewall_str(run: dict) -> str:
    return "fw" if run["manifest"].get("firewall", False) else "no-fw"


# ── load ──

def load_runs(commit_filter: str | None = None) -> list[dict]:
    runs: list[dict] = []
    if not RUNS.exists():
        return runs
    for d in sorted(RUNS.iterdir()):
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        with open(mf, encoding="utf-8") as f:
            manifest = json.load(f)

        if commit_filter and not manifest.get("git_commit", "").startswith(commit_filter):
            continue

        results: list[dict] = []
        rf = d / "results.jsonl"
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


# ── leak gate ──

def verify_no_holdout_leak(html: str) -> bool:
    """Scan for any holdout case ID (k01-k20, h01-h20) in the HTML."""
    holdout_ids = {f"{p}{i:02d}" for p in ("h", "k") for i in range(1, 21)}
    leaks = [hid for hid in holdout_ids if hid in html]
    if leaks:
        print(f"  ❌ HOLD-OUT LEAK: {leaks}", file=sys.stderr)
        return False
    return True


# ── render ──

def render(data: dict) -> str:
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
  h2 {{ font-size: 15px; margin: 28px 0 10px; color: var(--blue); }}
  .sub {{ color: var(--muted); font-size: 13px; }}
  main {{ padding: 24px 28px; max-width: 1200px; margin: 0 auto; }}
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
  .badge.amber {{ background:rgba(210,153,34,.15); color:var(--amber); }}
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
  .holdout-cell {{
    background: rgba(88,166,255,.06); color: var(--muted); font-style: italic;
    text-align: center; font-size: 12px;
  }}
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
  const gs = DATA.groups;
  const totalRuns = DATA.runs.length;
  sub.textContent = 'Runs: '+totalRuns+' · Groups: '+gs.length+
      ' · Rules R1–R6 · Misses U1/U2';

  let html = '';

  // Per-group summary cards
  html += '<h2>Run Groups (corpus × prompt × firewall)</h2><div class="strip">';
  for (const g of gs) {{
    const holdout = g.holdout;
    const s = g.latest_summary || {{}};
    const vbr = s.violations_by_rule || {{}};
    const mbk = s.misses_by_kind || {{}};
    const vtot = Object.values(vbr).reduce((a,b)=>a+b,0);
    const mtot = Object.values(mbk).reduce((a,b)=>a+b,0);
    const eab = (g.latest_escalations) || {{bot: '?', authority: '?'}};
    const n = g.run_count;
    const label = g.corpus + ' · ' + g.prompt + ' · ' + g.firewall;
    html += '<div class="card">'+
      '<div class="v">'+esc(label)+'</div>'+
      '<div class="num">'+esc(s.cases!==undefined?s.cases:'?')+' cases</div>'+
      '<div class="row"><span>violations</span>'+
        '<span class="badge '+(vtot===0?'green':'red')+'\">'+esc(vtot)+'</span></div>'+
      '<div class="row"><span>misses (U1/U2)</span>'+
        '<span class="badge '+(mtot===0?'green':'red')+'\">'+esc(mtot)+'</span></div>'+
      '<div class="row"><span>escalations</span>'+
        '<span class="badge amber">bot '+esc(eab.bot!==undefined?eab.bot:'?')+
        ' / auth '+esc(eab.authority!==undefined?eab.authority:'?')+'</span></div>'+
      '<div class="row"><span class="detail">'+esc(n)+' run'+(n>1?'s':'')+
        (holdout?' · holdout (sealed)':'')+'</span></div>'+
      '</div>';
  }}
  html += '</div>';

  // Rules matrix per group (not just per prompt)
  html += '<h2>Violations (R1–R6) and misses (U1/U2) by group</h2>';
  html += '<table><thead><tr><th>rule</th>';
  for (const g of gs) {{
    const label = g.prompt + ' ' + g.firewall;
    html += '<th>'+esc(label)+'</th>';
  }}
  html += '</tr></thead><tbody>';
  for (const rule of DATA.rules) {{
    html += '<tr><td class="num">'+esc(rule)+'</td>';
    for (const g of gs) {{
      const m = g.matrix || {{violations:{{}}, misses:{{}}}};
      const v = (m.violations||{{}})[rule];
      if (g.holdout) {{
        html += '<td class="holdout-cell">holdout</td>';
      }} else {{
        html += '<td>'+cell(v)+'</td>';
      }}
    }}
    html += '</tr>';
  }}
  for (const k of DATA.miss_kinds) {{
    html += '<tr><td class="num">'+esc(k)+' <span class="detail">miss</span></td>';
    for (const g of gs) {{
      const m = g.matrix || {{misses:{{}}}};
      const v = (m.misses||{{}})[k];
      if (g.holdout) {{
        html += '<td class="holdout-cell">holdout</td>';
      }} else {{
        html += '<td>'+cell(v)+'</td>';
      }}
    }}
    html += '</tr>';
  }}
  html += '</tbody></table>';

  // Case detail: latest run of each non-holdout group
  html += '<h2>Case detail — latest per group (holdouts omitted)</h2>';
  for (const g of gs) {{
    if (g.holdout) {{
      html += '<h3>'+esc(g.corpus)+' · '+esc(g.prompt)+' · '+esc(g.firewall)+
        ' <span class="detail">(holdout — counts only)</span></h3>';
      const s = g.latest_summary || {{}};
      html += '<p class="detail">'+esc(s.cases||0)+' cases, '+
        esc(s.failed||0)+' failed, violations: '+
        JSON.stringify(s.violations_by_rule||{{}})+
        ', misses: '+JSON.stringify(s.misses_by_kind||{{}})+'</p>';
      continue;
    }}
    const runs = g.runs || [];
    const last = runs[runs.length-1];
    if (!last) continue;
    html += '<h3>'+esc(g.corpus)+' · '+esc(g.prompt)+' · '+esc(g.firewall)+
      ' ('+esc(last.ts)+')</h3>';
    html += '<table><thead><tr><th>case</th><th>expected</th><th>violations</th><th>misses</th><th>result</th></tr></thead><tbody>';
    for (const r of last.results) {{
      const viol = (r.violations||[]).map(x=>x.rule||x).join(', ');
      const miss = (r.misses||[]).map(x=>x.kind||x).join(', ');
      const expV = (r.expected_violations||[]).join(', ') || '—';
      const eo = r.expected_outcome;
      let expO = '—';
      if (eo) {{
        if (eo.refund !== undefined) expO = 'refund $'+eo.refund;
        else if (eo.escalate) expO = 'escalate';
        else expO = JSON.stringify(eo);
      }}
      const result = (viol||miss) ? 'fail' : 'pass';
      html += '<tr>'+
        '<td>'+esc(r.case_id)+'<div class=\"detail\">'+esc(r.title)+'</div></td>'+
        '<td class=\"num\">'+esc(expV)+' / '+esc(expO)+'</td>'+
        '<td class=\"'+(viol?'bad':'zero')+'\">'+esc(viol||'—')+'</td>'+
        '<td class=\"'+(miss?'bad':'zero')+'\">'+esc(miss||'—')+'</td>'+
        '<td class=\"'+(result==='pass'?'zero':'bad')+'\">'+esc(result)+'</td>'+
        '</tr>';
    }}
    html += '</tbody></table>';
  }}

  document.getElementById('main').innerHTML = html;

  // footer: from the last run overall
  const lastRun = DATA.runs[DATA.runs.length-1];
  const f = document.getElementById('footer');
  if (lastRun) {{
    f.innerHTML = 'Latest run: '+esc(lastRun.ts)+' · git '+
      esc(lastRun.git_commit||'?')+
      (lastRun.git_dirty ? ' <span class=\"dirty\">(dirty)</span>' : ' <span class=\"clean\">(clean)</span>')+
      ' · verifier '+esc(lastRun.verifier_version||'?')+
      ' · holdout-safe &#10003;';
  }}
}}

render();
</script>
</body>
</html>"""


# ── aggregate ──

def _summary_stats(runs: list[dict], holdout: bool) -> dict:
    """Aggregate from latest run only — manifest summary is authoritative."""
    if not runs:
        return {}
    latest = runs[-1]
    s = latest["summary"]
    result = {
        "cases": s.get("cases", 0),
        "failed": s.get("failed", 0),
        "violations_by_rule": s.get("violations_by_rule", {}),
        "misses_by_kind": s.get("misses_by_kind", {}),
        "escalations_by_actor": s.get("escalations_by_actor", {"bot": 0, "authority": 0}),
    }
    if holdout:
        # Holdout: NULL the rule/miss detail — counts-only
        result["violations_by_rule"] = {
            r: "holdout" for r in RULES if r in result["violations_by_rule"]
        }
        result["misses_by_kind"] = {
            k: "holdout" for k in MISS_KINDS if k in result["misses_by_kind"]
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", type=str, default=None,
                        help="Filter runs to a specific commit prefix (e.g. 5423ab2)")
    args = parser.parse_args()

    runs = load_runs(commit_filter=args.commit)
    if not runs:
        print("No runs found.", file=sys.stderr)
        sys.exit(1)

    # Group: (corpus_label, prompt_version, firewall_str)
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for r in runs:
        key = (corpus_label(r), prompt_version(r["manifest"]), firewall_str(r))
        groups.setdefault(key, []).append(r)

    # Newsafe data shape — holdout run data is never embedded
    safe_runs = []
    for r in runs:
        holdout = is_holdout_run(r)
        safe_runs.append({
            "ts": r["ts"],
            "corpus": corpus_label(r),
            "prompt": prompt_version(r["manifest"]),
            "firewall": firewall_str(r),
            "holdout": holdout,
            "model": r["manifest"].get("model", "?"),
            "git_commit": r["manifest"].get("git_commit", "?"),
            "git_dirty": r["manifest"].get("git_dirty", "?"),
            "prompt_sha256": (r["manifest"].get("prompt_sha256", "") or "")[:12],
            "verifier_version": r["manifest"].get("verifier_version", "?"),
            "summary": r["summary"] if not holdout else {},
            # NEVER embed holdout results
            "results": [] if holdout else r["results"],
        })

    # Group aggregations
    group_list = []
    for (corp, ver, fw), gruns in sorted(groups.items()):
        holdout = is_holdout_run(gruns[0])
        stats = _summary_stats(gruns, holdout)
        group_list.append({
            "corpus": corp,
            "prompt": ver,
            "firewall": fw,
            "holdout": holdout,
            "run_count": len(gruns),
            "latest_ts": gruns[-1]["ts"],
            "latest_summary": gruns[-1]["summary"] if not holdout else {},
            "latest_escalations": gruns[-1]["summary"].get("escalations_by_actor",
                                                           {"bot": "?", "authority": "?"}),
            "matrix": {
                "violations": stats.get("violations_by_rule", {}),
                "misses": stats.get("misses_by_kind", {}),
            },
            "runs": safe_runs[-len(gruns):] if not holdout else [],
        })

    data = {
        "runs": safe_runs,
        "groups": group_list,
        "rules": RULES,
        "miss_kinds": MISS_KINDS,
    }

    html = render(data)

    # Gate: verify no holdout leaks
    if not verify_no_holdout_leak(html):
        print("BLOCKED: HTML contains holdout case IDs. Not written.", file=sys.stderr)
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT}  ({len(runs)} runs, {len(group_list)} groups)")


if __name__ == "__main__":
    main()