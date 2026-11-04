#!/usr/bin/env python3
"""Generate a video-friendly dashboard FRAME from evidence/5423ab2 only.

Difference from generate.py:
  - reads evidence/5423ab2/ (17 scored runs), NOT runs/ (19)
  - violations and misses in SEPARATE columns (not stacked rows)
  - one row per (prompt version x firewall), totals across non-holdout corpora
  - holdout (h*) shown sealed — aggregate counts only, no IDs/traces
  - clean single-screen layout for the demo video

Usage: python3 dashboard/generate_frame.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "evidence" / "5423ab2"
OUT = REPO / "dashboard" / "frame.html"

RULES = ["R1", "R2", "R3", "R4", "R5", "R6"]
MISS_KINDS = ["U1", "U2"]
HOLDOUT_PREFIXES = {"h", "k"}


def corpus_label(run: dict) -> str:
    results = run["results"]
    if not results:
        return "unknown"
    cid = results[0].get("case_id", "")
    p = cid[:1]
    return {
        "h": "holdout_attack",
        "k": "holdout_useful",
        "n": "named",
        "a": "attacks/wonder",
        "l": "attacks/live",
    }.get(p, "unknown")


def prompt_version(m: dict) -> str:
    p = m.get("prompt_path", "") or ""
    if not p:
        return "v1"
    base = p.rsplit("/", 1)[-1]
    return base[:-4] if base.endswith(".txt") else (base or "v1")


def fw_str(m: dict) -> str:
    return "firewall" if m.get("firewall", False) else "no-fw"


def load_runs() -> list[dict]:
    runs = []
    for d in sorted(EVIDENCE.iterdir()):
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        results = []
        rf = d / "results.jsonl"
        if rf.exists():
            for line in rf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    results.append(json.loads(line))
        runs.append({"ts": d.name, "manifest": manifest, "results": results})
    return runs


def main() -> None:
    runs = load_runs()
    if not runs:
        print("No runs found.", flush=True)
        return

    # classify holdout
    for r in runs:
        r["holdout"] = bool(r["results"]) and r["results"][0]["case_id"][:1] in HOLDOUT_PREFIXES

    non_holdout = [r for r in runs if not r["holdout"]]
    holdout = [r for r in runs if r["holdout"]]

    # aggregate violations/misses per (prompt, firewall) across non-holdout corpora
    # key -> {violations: {rule: n}, misses: {kind: n}, cases: n, failed: n, runs: n}
    agg: dict[tuple[str, str], dict] = {}
    corpus_order = ["named", "attacks/wonder", "attacks/live"]
    for r in non_holdout:
        key = (prompt_version(r["manifest"]), fw_str(r["manifest"]))
        s = r["manifest"].get("summary", {})
        a = agg.setdefault(key, {
            "violations": {rule: 0 for rule in RULES},
            "misses": {k: 0 for k in MISS_KINDS},
            "cases": 0, "failed": 0, "runs": 0,
        })
        for rule, n in s.get("violations_by_rule", {}).items():
            if rule in a["violations"]:
                a["violations"][rule] += n
        for k, n in s.get("misses_by_kind", {}).items():
            if k in a["misses"]:
                a["misses"][k] += n
        a["cases"] += s.get("cases", 0)
        a["failed"] += s.get("failed", 0)
        a["runs"] += 1

    # holdout aggregate
    ho_cases = sum(r["manifest"].get("summary", {}).get("cases", 0) for r in holdout)
    ho_runs = len(holdout)

    rows = []
    # stable order: v1 no-fw, v2 no-fw, v3 no-fw, v1 fw, v3 fw
    order = [("v1", "no-fw"), ("v2", "no-fw"), ("v3", "no-fw"),
             ("v1", "firewall"), ("v3", "firewall")]
    for key in order:
        if key in agg:
            a = agg[key]
            vtot = sum(a["violations"].values())
            mtot = sum(a["misses"].values())
            rows.append({
                "prompt": key[0], "fw": key[1],
                "vtot": vtot, "mtot": mtot,
                "vdetail": {r: a["violations"][r] for r in RULES if a["violations"][r]},
                "mdetail": {k: a["misses"][k] for k in MISS_KINDS if a["misses"][k]},
                "cases": a["cases"], "failed": a["failed"], "runs": a["runs"],
            })

    data = {
        "rows": rows,
        "holdout": {"runs": ho_runs, "cases": ho_cases},
        "total_runs": len(runs),
        "non_holdout_runs": len(non_holdout),
    }
    html = render(data)

    # leak gate
    holdout_ids = {f"{p}{i:02d}" for p in ("h", "k") for i in range(1, 21)}
    leaks = [hid for hid in holdout_ids if hid in html]
    if leaks:
        print(f"BLOCKED: holdout leak {leaks}", flush=True)
        return

    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(runs)} runs, {len(rows)} frame rows, holdout sealed)", flush=True)


def render(data: dict) -> str:
    dj = json.dumps(data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Support Bot Rescue — Repair Frame</title>
<style>
  :root {{ --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#c9d1d9;
          --muted:#8b949e; --red:#f85149; --green:#3fb950; --amber:#d29922;
          --blue:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         font-size:16px; line-height:1.5; }}
  header {{ padding:22px 32px; border-bottom:1px solid var(--border); background:var(--panel); }}
  h1 {{ margin:0 0 4px; font-size:22px; }}
  .sub {{ color:var(--muted); font-size:13px; }}
  main {{ padding:28px 32px; max-width:960px; margin:0 auto; }}
  table {{ width:100%; border-collapse:collapse; background:var(--panel);
          border:1px solid var(--border); margin-top:10px; }}
  th, td {{ padding:12px 16px; text-align:left; border-bottom:1px solid var(--border); }}
  th {{ color:var(--muted); font-weight:600; font-size:13px; white-space:nowrap; }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ font-variant-numeric:tabular-nums; }}
  .zero {{ color:var(--green); font-weight:600; }}
  .bad {{ color:var(--red); font-weight:600; }}
  .col-v {{ color:var(--red); }}
  .col-m {{ color:var(--amber); }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:12px;
           font-size:12px; font-weight:600; }}
  .badge.fw {{ background:rgba(88,166,255,.15); color:var(--blue); }}
  .badge.nofw {{ background:rgba(139,148,158,.15); color:var(--muted); }}
  .detail {{ color:var(--muted); font-size:12px; }}
  .sealed {{ background:rgba(88,166,255,.06); color:var(--muted);
            font-style:italic; text-align:center; }}
</style>
</head>
<body>
<header>
  <h1>Support Bot Rescue — Refund-Policy Repair</h1>
  <div class="sub" id="sub"></div>
</header>
<main id="main"></main>
<script>
const DATA = {dj};
function esc(s) {{ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }}
function n(v) {{ return (v===0)?'<span class="num zero">0</span>'
  :'<span class="num bad">'+esc(v)+'</span>'; }}
function render() {{
  const sub = document.getElementById('sub');
  sub.textContent = 'evidence/5423ab2 · '+DATA.total_runs+' runs · '+
    DATA.non_holdout_runs+' scored (holdout sealed) · rules R1–R6 · misses U1/U2';

  let h = '';
  h += '<h2 style="margin-top:0">Violations vs misses — separate columns</h2>';
  h += '<table><thead><tr>'+
    '<th>prompt</th><th>firewall</th>'+
    '<th class="col-v">violations</th><th class="col-m">misses</th>'+
    '<th>cases</th><th>failed</th><th>detail</th>'+
    '</tr></thead><tbody>';
  for (const r of DATA.rows) {{
    const fwb = r.fw==='firewall'
      ? '<span class="badge fw">firewall</span>'
      : '<span class="badge nofw">no-fw</span>';
    const vd = Object.entries(r.vdetail).map(([k,v])=>k+':'+v).join(' ');
    const md = Object.entries(r.mdetail).map(([k,v])=>k+':'+v).join(' ');
    h += '<tr>'+
      '<td class="num">'+esc(r.prompt)+'</td>'+
      '<td>'+fwb+'</td>'+
      '<td class="col-v">'+n(r.vtot)+'</td>'+
      '<td class="col-m">'+n(r.mtot)+'</td>'+
      '<td class="num">'+esc(r.cases)+'</td>'+
      '<td class="num">'+n(r.failed)+'</td>'+
      '<td class="detail">'+esc(vd)+' '+(md?esc('· '+md):'')+'</td>'+
      '</tr>';
  }}
  h += '</tbody></table>';

  h += '<h2>Holdout (sealed — counts only)</h2>';
  h += '<table><thead><tr><th>corpus</th><th>runs</th><th>cases</th><th>status</th></tr></thead><tbody>';
  h += '<tr><td>holdout_attack</td>'+
    '<td class="num">'+esc(DATA.holdout.runs)+'</td>'+
    '<td class="num">'+esc(DATA.holdout.cases)+'</td>'+
    '<td class="sealed">sealed — not opened by dashboard</td></tr>';
  h += '</tbody></table>';

  document.getElementById('main').innerHTML = h;
}}
render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
