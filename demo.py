"""Offline live demo: play the Support Bot Rescue story from shipped evidence.

Usage: py -3 demo.py [--fast] [--no-color]

Every number is computed at run time from evidence/5423ab2 (the 13
non-holdout scored runs). No network, no API key, standard library only.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE_DIR = ROOT / "evidence" / "5423ab2"
POLICY_PATH = ROOT / "maple" / "policy.md"
WORKTREE_VERIFIER = ROOT.parent / "sbr-5423ab2" / "verify_manifest.py"
SCORED_COMMIT = "5423ab2"
PAUSE_SECONDS = 1.4

_use_color = False


def _heading(text: str) -> str:
    if _use_color:
        return f"\033[1;36m{text}\033[0m"
    return text


def _pause(fast: bool) -> None:
    if not fast:
        time.sleep(PAUSE_SECONDS)


# --- evidence loading -------------------------------------------------

def _corpus_of(manifest: dict) -> str:
    corpora = [k for k in manifest.get("files", {}) if k.startswith("corpus/") and k.endswith(".jsonl")]
    return corpora[0] if corpora else ""


def load_shown_runs() -> list[dict]:
    """The non-holdout runs under evidence/5423ab2, sorted by run id.

    A run is a holdout run when its manifest binds a holdout corpus; those
    runs are skipped entirely (their results and traces are never read).
    """
    runs = []
    for run_dir in sorted(EVIDENCE_DIR.iterdir()):
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        corpus = _corpus_of(manifest)
        if "holdout" in corpus:
            continue
        runs.append({
            "id": run_dir.name,
            "dir": run_dir,
            "manifest": manifest,
            "corpus": corpus,
            "prompt": manifest.get("prompt_path", ""),
            "firewall": bool(manifest.get("firewall")),
        })
    return runs


def _find_run(runs: list[dict], prompt_file: str, firewall: bool) -> dict:
    for run in runs:
        if run["corpus"] == "corpus/named.jsonl" and run["prompt"].endswith(f"/{prompt_file}") and run["firewall"] is firewall:
            return run
    raise SystemExit(f"demo: expected scored run for {prompt_file} (firewall={firewall}) not found in {EVIDENCE_DIR}")


def _read_results(run: dict) -> list[dict]:
    path = run["dir"] / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def count_run(run: dict) -> dict:
    rows = _read_results(run)
    violations = Counter(v["rule"] for row in rows for v in row.get("violations", []))
    misses = Counter(m["kind"] for row in rows for m in row.get("misses", []))
    failed = sum(1 for row in rows if row.get("failed", bool(row.get("violations") or row.get("misses"))))
    return {"cases": len(rows), "failed": failed, "violations": violations, "misses": misses}


def _fmt_counter(counter: Counter) -> str:
    return ", ".join(f"{key}:{counter[key]}" for key in sorted(counter))


def format_counts(counts: dict, *, breakdown: bool = True) -> str:
    v_total = sum(counts["violations"].values())
    m_total = sum(counts["misses"].values())
    text = f"cases={counts['cases']} failed={counts['failed']} violations={v_total}"
    if breakdown and v_total:
        text += f" ({_fmt_counter(counts['violations'])})"
    text += f" misses={m_total}"
    if breakdown and m_total:
        text += f" ({_fmt_counter(counts['misses'])})"
    return text


def _money(value) -> str:
    return f"${float(value):.2f}"


# --- beats ------------------------------------------------------------

def beat_policy() -> None:
    print(_heading("1. The policy (Maple & Co)"))
    for line in POLICY_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"- \*\*(R\d+) - ([^*]+?)\.\*\*\s*(.*)", line.strip())
        if match:
            rule, title, detail = match.groups()
            detail = detail.strip()
            print(f"{rule} - {title.strip()}" + (f": {detail}" if detail else ""))
    print("Judge: deterministic code, no LLM")


def _print_run_counts(label: str, run: dict) -> dict:
    counts = count_run(run)
    print(f"{label} [{run['id']}]")
    print(f"Counts: {format_counts(counts)}")
    return counts


def beat_v1(runs: list[dict]) -> dict:
    run = _find_run(runs, "v1.txt", False)
    print(_heading("2. The original prompt v1, firewall off"))
    counts = _print_run_counts("v1 (original), firewall off", run)
    rows = _read_results(run)
    failing = next((row for row in rows if row.get("violations")), None)
    if failing is not None:
        case_id = failing["case_id"]
        rules = ", ".join(sorted({v["rule"] for v in failing["violations"]}))
        print(f"Failing case: {case_id} ({failing.get('title', '')}) - violation(s): {rules}")
        trace_rel = run["manifest"]["traces"][case_id]["path"]
        trace_data = json.loads((run["dir"] / trace_rel).read_text(encoding="utf-8"))
        lines = [ln.strip() for ln in str(trace_data.get("reply", "")).splitlines() if ln.strip()]
        quote = next(
            (ln for ln in lines if "refunded" in ln.lower()),
            next((ln for ln in lines if "refund" in ln.lower()), lines[-1] if lines else ""),
        )
        if len(quote) > 180:
            quote = quote[:177].rstrip() + "..."
        print(f'Quote from stored trace: "{quote}"')
    return counts


def beat_v2(runs: list[dict]) -> dict:
    run = _find_run(runs, "v2.txt", False)
    print(_heading("3. The first fix v2, firewall off"))
    counts = _print_run_counts("v2, firewall off", run)
    rows = _read_results(run)
    failing = [row for row in rows if row.get("failed", bool(row.get("violations") or row.get("misses")))]
    if failing and not counts["violations"] and counts["misses"]:
        row = failing[0]
        kinds = ", ".join(sorted({m["kind"] for m in row.get("misses", [])}))
        details = "; ".join(m.get("detail", "") for m in row.get("misses", []))
        print(
            f"Highlight: its remaining failure is a usefulness miss ({kinds}), not a rule violation: "
            f"{row['case_id']} - a refused eligible refund ({details})"
        )
    return counts


def beat_v3(runs: list[dict]) -> dict:
    run = _find_run(runs, "v3.txt", False)
    print(_heading("4. The hardened prompt v3, firewall off"))
    author = run["manifest"].get("prompt_author_model")
    label = "v3 (hardened, written by Muse Wonder), firewall off"
    if author:
        label += f" - prompt author (from manifest): {author}"
    counts = count_run(run)
    print(f"{label} [{run['id']}]")
    print(f"Counts: {format_counts(counts)}")
    return counts


def beat_v1_firewall(runs: list[dict]) -> dict:
    run = _find_run(runs, "v1.txt", True)
    print(_heading("5. The original prompt v1 behind the firewall"))
    counts = _print_run_counts("v1 (original), firewall on", run)
    case_id = "n05_over_total"
    trace_rel = run["manifest"]["traces"][case_id]["path"]
    trace_data = json.loads((run["dir"] / trace_rel).read_text(encoding="utf-8"))
    trace = trace_data.get("trace", [])
    proposal = next((e for e in trace if e.get("name") == "propose_refund"), None)
    if proposal is not None:
        args = proposal.get("args", {})
        result = proposal.get("result", {}) if isinstance(proposal.get("result"), dict) else {}
        print(f"Case {case_id}:")
        print(f"- Bot proposed: {_money(args.get('amount', 0))} for order {args.get('order_id', '')}")
        denial = result.get("denied", "")
        detail = result.get("detail", "")
        print(f"- Authority denial: {denial} - {detail}" if denial else f"- Authority denial: {detail}")
        later = [e for e in trace if isinstance(e.get("index"), int) and e["index"] > proposal.get("index", -1)]
        lines = [ln.strip() for ln in str(trace_data.get("reply", "")).splitlines() if ln.strip()]
        next_step = lines[-1] if lines else ""
        if later:
            print(f"- What the bot did next: {later[0].get('name', 'another tool call')}")
        else:
            print(f'- What the bot did next: no further tool call; it asked: "{next_step}"')
    return counts


# --- re-check ---------------------------------------------------------

def _fallback_verifier(temp_root: Path, *, include_holdout: bool = False) -> Path | None:
    """Extract the verifier from commit 5423ab2 into a temporary directory.

    Holdout files are skipped unless `include_holdout` is set (verify_claims
    needs them to re-verify the holdout-run manifests).
    """
    git = shutil.which("git")
    if not git:
        return None
    try:
        archive = subprocess.run(
            [git, "-C", str(ROOT), "archive", SCORED_COMMIT],
            capture_output=True, timeout=60,
        )
        if archive.returncode != 0 or not archive.stdout:
            return None
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            for member in tar.getmembers():
                name = member.name.replace("\\", "/")
                if not member.isfile() or ("holdout" in name and not include_holdout) or name.endswith(".sha256"):
                    continue
                if name.startswith("/") or ".." in Path(name).parts:
                    continue
                source = tar.extractfile(member)
                if source is None:
                    continue
                dest = temp_root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(source.read())
        shown = subprocess.run(
            [git, "-C", str(ROOT), "show", f"{SCORED_COMMIT}:verify_manifest.py"],
            capture_output=True, timeout=60,
        )
        if shown.returncode != 0 or not shown.stdout:
            return None
        verifier = temp_root / "verify_manifest.py"
        verifier.write_bytes(shown.stdout)
        return verifier if verifier.is_file() else None
    except (OSError, subprocess.SubprocessError, tarfile.TarError):
        return None


def beat_recheck(runs: list[dict]) -> int:
    print(_heading("6. Re-check: re-verify the shown manifests with the verifier from 5423ab2"))
    temp_root = None
    verifier = WORKTREE_VERIFIER if WORKTREE_VERIFIER.is_file() else None
    if verifier is None:
        temp_root = ROOT / f".tmp-demo-5423ab2-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True)
        verifier = _fallback_verifier(temp_root)
    if verifier is None:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)
        print("Re-check skipped: no verifier from commit 5423ab2 available (no ../sbr-5423ab2 worktree, git extraction failed).")
        print("Run these commands instead:")
        print("git worktree add ../sbr-5423ab2 5423ab2")
        print(r"for /d %r in (evidence\5423ab2\*) do py -3 ..\sbr-5423ab2\verify_manifest.py %r\manifest.json")
        return 0
    ok = 0
    try:
        for run in runs:
            manifest_path = (run["dir"] / "manifest.json").resolve()
            try:
                proc = subprocess.run(
                    [sys.executable, str(verifier), str(manifest_path)],
                    capture_output=True, text=True, timeout=120,
                )
                first = (proc.stdout or "").strip().splitlines()
                detail = first[0] if first else (proc.stderr or "").strip().splitlines()[:1]
                detail = detail[0] if isinstance(detail, list) and detail else str(detail)
            except (OSError, subprocess.SubprocessError) as exc:
                proc, detail = None, str(exc)
            if proc is not None and proc.returncode == 0 and detail.startswith("OK"):
                ok += 1
                print(f"OK {run['id']}: {detail}")
            else:
                print(f"MISMATCH {run['id']}: {detail}")
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)
    print(f"{ok} of {len(runs)} OK")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline live demo from shipped evidence (evidence/5423ab2).")
    parser.add_argument("--fast", action="store_true", help="remove all pauses")
    parser.add_argument("--no-color", action="store_true", help="plain output, no ANSI colour")
    args = parser.parse_args(argv)

    global _use_color
    _use_color = not args.no_color and sys.stdout.isatty()

    runs = load_shown_runs()
    print(_heading("Support Bot Rescue - live demo (offline, computed from shipped evidence)"))
    print(f"Evidence: evidence/5423ab2 - {len(runs)} shown runs, every number computed at run time.")
    _pause(args.fast)

    beat_policy()
    _pause(args.fast)
    counts_v1 = beat_v1(runs)
    _pause(args.fast)
    counts_v2 = beat_v2(runs)
    _pause(args.fast)
    counts_v3 = beat_v3(runs)
    _pause(args.fast)
    counts_v1_fw = beat_v1_firewall(runs)
    _pause(args.fast)
    verified = beat_recheck(runs)
    _pause(args.fast)

    print(_heading("7. Close"))
    print("Find it. Fix it. Re-run it. Verify it.")
    print(f"v1 (firewall off): {format_counts(counts_v1)}")
    print(f"v2 (firewall off): {format_counts(counts_v2)}")
    print(f"v3 (firewall off): {format_counts(counts_v3)}")
    print(f"v1+firewall: {format_counts(counts_v1_fw)}")

    return 0 if runs and verified == len(runs) else 1


if __name__ == "__main__":
    sys.exit(main())
