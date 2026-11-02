"""Known-answer agreement check: compiled spec vs hand-written verifier.

Usage: py -3 -m compiler.agreement compiled/maple.spec.json

Runs both judges over every trace of the non-holdout runs in
evidence/5423ab2/. A run whose manifest names a holdout corpus is skipped
entirely (its traces are never opened).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compiler.dsl import validate_spec  # noqa: E402
from compiler.spec_judge import judge_trace  # noqa: E402
from sandbox.tools import load_world  # noqa: E402
from verifier.rules import check_all  # noqa: E402

EVIDENCE_ROOT = ROOT / "evidence" / "5423ab2"
ORDERS_PATH = ROOT / "maple" / "orders.json"
POLICY_PATH = ROOT / "maple" / "policy.md"
FORBIDDEN_NAMES = {"holdout.jsonl", "holdout_useful.jsonl"}


def _norm(text: str) -> str:
    return " ".join(str(text).replace("**", "").split())


def rule_mapping(spec, policy_text: str) -> dict[str, str | None]:
    """Map compiled rule id -> R1-R6 by locating its quote in the policy."""
    bullets: list[tuple[str, str]] = []
    current: str | None = None
    buf: list[str] = []
    for line in policy_text.splitlines():
        m = re.match(r"\s*-\s+\*\*(R\d+)\b", line)
        if m:
            if current:
                bullets.append((current, " ".join(buf)))
            current, buf = m.group(1), [line]
        elif current:
            buf.append(line)
    if current:
        bullets.append((current, " ".join(buf)))
    mapping: dict[str, str | None] = {}
    for rule in spec.rules:
        quote = _norm(rule.quote)
        found = None
        for rid, text in bullets:
            norm_text = _norm(text)
            sentences = re.split(r"(?<=[.!?])\s+", norm_text)
            if quote in norm_text or any(quote in _norm(s) or _norm(s) in quote for s in sentences if _norm(s)):
                found = rid
                break
        if found is None:
            m = re.search(r"\b(R\d+)\b", rule.quote)
            found = m.group(1) if m else None
        mapping[rule.id] = found
    return mapping


def _manifest_corpora(manifest: dict) -> list[str]:
    rels = [k for k in manifest.get("files", {}) if k.startswith("corpus/") and k.endswith(".jsonl")]
    extra = manifest.get("corpus")
    if isinstance(extra, str):
        rels.append(extra)
    elif isinstance(extra, list):
        rels.extend(str(x) for x in extra)
    return rels


def run_agreement(spec_path: Path | str, evidence_root: Path | str = EVIDENCE_ROOT,
                  orders_path: Path | str = ORDERS_PATH, policy_path: Path | str = POLICY_PATH,
                  out_path: Path | str | None = None) -> dict[str, Any]:
    spec_path = Path(spec_path)
    policy_text = Path(policy_path).read_text(encoding="utf-8")
    spec = validate_spec(json.loads(spec_path.read_text(encoding="utf-8")), policy_text=policy_text)
    mapping = rule_mapping(spec, policy_text)
    world = load_world(orders_path)
    cases: list[dict] = []
    disagreements: list[dict] = []
    runs = 0
    for run_dir in sorted(Path(evidence_root).iterdir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(Path(rel).name in FORBIDDEN_NAMES for rel in _manifest_corpora(manifest)):
            continue  # holdout run: skip entirely, never open its traces
        runs += 1
        for case_id, info in manifest.get("traces", {}).items():
            payload = json.loads((run_dir / info["path"]).read_text(encoding="utf-8"))
            state = {"today": world["today"], "orders": world["orders"], **payload.get("final_state", {})}
            hand = check_all(payload.get("trace") or [], state, payload.get("reply") or "")
            raw_compiled = judge_trace(spec, payload.get("trace") or [], state, payload.get("reply") or "")
            compiled = [{**v, "rule": mapping.get(v["rule"]) or v["rule"]} for v in raw_compiled]
            hand_keys = {(v["rule"], v["trace_index"]) for v in hand}
            compiled_keys = {(v["rule"], v["trace_index"]) for v in compiled}
            agree = hand_keys == compiled_keys
            entry = {"run": run_dir.name, "case_id": case_id,
                     "compiled": sorted({v["rule"] for v in compiled}),
                     "hand_written": sorted({v["rule"] for v in hand}), "agree": agree}
            cases.append(entry)
            if not agree:
                involved = sorted({r for r, _ in hand_keys ^ compiled_keys})
                disagreements.append({**entry, "rules_involved": involved,
                                      "compiled_violations": compiled, "hand_written_violations": hand})
    report = {"spec": str(spec_path), "mapping": mapping, "runs": runs,
              "total": len(cases), "agreement": sum(c["agree"] for c in cases),
              "cases": cases, "disagreements": disagreements}
    if out_path is not None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _default_out(spec_path: Path) -> Path:
    name = spec_path.name
    if name.endswith(".spec.json"):
        return spec_path.with_name(name[: -len(".spec.json")] + ".agreement.json")
    return spec_path.with_suffix(".agreement.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="compiled spec, e.g. compiled/maple.spec.json")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    spec_path = Path(a.spec)
    out = Path(a.out) if a.out else _default_out(spec_path)
    try:
        report = run_agreement(spec_path, out_path=out)
    except (ValueError, OSError) as e:
        print(f"error: {e}")
        return 2
    for case in report["cases"]:
        mark = "OK" if case["agree"] else "DISAGREE"
        print(f"{case['run']}/{case['case_id']}: compiled={case['compiled']} hand_written={case['hand_written']} {mark}")
    for d in report["disagreements"]:
        print(f"disagreement: {d['run']}/{d['case_id']} rules={d['rules_involved']} "
              f"compiled={d['compiled_violations']} hand_written={d['hand_written_violations']}")
    print(f"agreement: {report['agreement']} of {report['total']} traces")
    print(f"wrote: {out}")
    return 0 if not report["disagreements"] else 1


if __name__ == "__main__":
    sys.exit(main())
