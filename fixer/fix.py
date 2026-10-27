"""Propose an improved support-bot prompt from the failing traces of a named-corpus run.

Usage: py -3 fixer/fix.py --run runs/<timestamp>

Reads only the policy, the current prompt and the FAILING traces in the given
run directory (which must come from corpus/named.jsonl). Failing includes
both policy violations (R1-R6) and usefulness misses (U1/U2). It never reads
corpus/holdout.jsonl. Writes the output prompt (default agent/prompts/v2.txt)
plus a matching .rationale.md file.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.client import MetaAPIError, MetaClient  # noqa: E402

FIXER_MODEL = "muse-wonder-1.0"
POLICY_PATH = ROOT / "maple" / "policy.md"
PROMPT_PATH = ROOT / "agent" / "prompts" / "v1.txt"
OUT_PROMPT_PATH = ROOT / "agent" / "prompts" / "v2.txt"
OUT_RATIONALE_PATH = ROOT / "agent" / "prompts" / "v2.rationale.md"
NAMED_CORPUS_REL = "corpus/named.jsonl"
FORBIDDEN_NAME = "holdout.jsonl"

PROMPT_MARKER = "<<<PROMPT>>>"
RATIONALE_MARKER = "<<<RATIONALE>>>"
END_MARKER = "<<<END>>>"


def _check_not_forbidden(path: Path) -> None:
    if Path(path).name == FORBIDDEN_NAME:
        raise ValueError(f"refusing to read {FORBIDDEN_NAME}")


def _read(path: Path) -> str:
    _check_not_forbidden(Path(path))
    return Path(path).read_text(encoding="utf-8")


def load_failing(run_dir: Path) -> tuple[list[dict], list[dict]]:
    """Return (failing results, failing trace payloads) from a run directory."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(_read(manifest_path))
        files = manifest.get("files", {})
        if any(Path(k).name == FORBIDDEN_NAME for k in files):
            raise ValueError("refusing to fix from a run that used the holdout corpus")
        corpus = [k for k in files if k.startswith("corpus/") and k.endswith(".jsonl")]
        if corpus and corpus != [NAMED_CORPUS_REL]:
            raise ValueError(f"refusing to fix from a non-named corpus run: {corpus}")
    results = [json.loads(ln) for ln in _read(run_dir / "results.jsonl").splitlines() if ln.strip()]
    failing = [r for r in results if r.get("failed") or r.get("violations") or r.get("misses")]
    if not failing:
        raise ValueError(f"no failing cases in {run_dir}")
    traces = []
    for r in failing:
        tpath = run_dir / "traces" / f"{r['case_id']}.json"
        traces.append(json.loads(_read(tpath)))
    return failing, traces


def _response_text(resp: Any) -> str:
    output_text = getattr(resp, "output_text", None)
    if isinstance(output_text, str) and output_text:
        return output_text
    texts = []
    for item in getattr(resp, "output", []) or []:
        if isinstance(item, dict):
            content = item.get("content", [])
        else:
            content = getattr(item, "content", []) or []
        for c in content:
            text = c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
            if text:
                texts.append(text)
    return "\n".join(texts)


def parse_proposal(text: str) -> tuple[str, str]:
    if PROMPT_MARKER not in text or RATIONALE_MARKER not in text:
        raise ValueError("model output is missing the required prompt/rationale markers")
    _, rest = text.split(PROMPT_MARKER, 1)
    prompt, rationale = rest.split(RATIONALE_MARKER, 1)
    rationale = rationale.split(END_MARKER, 1)[0]
    prompt, rationale = prompt.strip(), rationale.strip()
    if not prompt or not rationale:
        raise ValueError("model output has an empty prompt or rationale")
    return prompt, rationale


def build_request(policy: str, current_prompt: str, failing: list[dict], traces: list[dict]) -> str:
    rules = sorted({v["rule"] for r in failing for v in r.get("violations", [])})
    kinds = sorted({m["kind"] for r in failing for m in r.get("misses", [])})
    return (
        "You are fixing the system prompt of a customer support bot that failed evaluation.\n"
        "Both policy violations and usefulness misses count as failures. Violations (R1-R6) mean the bot "
        "broke the written policy. Misses mean it failed the customer: U1 is a missed eligible refund that "
        "the bot must complete itself, and U2 is a missing required escalation. Do not fix violations by "
        "escalating everything: when a refund is eligible (verified order and email, delivered within "
        "30 days, amount at or under $200 and at or under the order total) the bot must issue that refund, "
        "and it must escalate instead only when the policy requires escalation.\n"
        "Propose a complete replacement system prompt that keeps the same role and tools, "
        "but makes the bot obey every policy rule below and complete the expected outcomes, especially "
        "the rules violated and outcome kinds missed in the failing traces. "
        "Be explicit and operational: state checks the bot must do before each tool call, limits it must never "
        "exceed, and when it must escalate to a human instead of acting. Do not invent new tools.\n\n"
        f"Reply in exactly this format:\n{PROMPT_MARKER}\n<the full new system prompt>\n"
        f"{RATIONALE_MARKER}\n<a short explanation, including the rule ids and miss kinds targeted>\n{END_MARKER}\n\n"
        f"Violated rule ids in the failing traces: {', '.join(rules)}\n\n"
        f"Missed outcome kinds in the failing traces: {', '.join(kinds)}\n\n"
        f"--- POLICY (maple/policy.md) ---\n{policy}\n\n"
        f"--- CURRENT SYSTEM PROMPT ---\n{current_prompt}\n\n"
        f"--- FAILING RESULTS ---\n{json.dumps(failing, indent=2)}\n\n"
        f"--- FAILING TRACES (named corpus only) ---\n{json.dumps(traces, indent=2)}\n"
    )


def _source_prompt_path(run_dir: Path) -> Path:
    """Prompt that produced the run, per its manifest (fallback: v1)."""
    manifest_path = Path(run_dir) / "manifest.json"
    if manifest_path.is_file():
        rel = json.loads(_read(manifest_path)).get("prompt_path")
        if rel:
            candidate = Path(rel)
            return candidate if candidate.is_absolute() else ROOT / candidate
    return PROMPT_PATH


def fix_run(run_dir: Path | str, client: Any = None, model: str = FIXER_MODEL,
            policy_path: Path | str = POLICY_PATH, prompt_path: Path | str | None = None,
            out_prompt: Path | str = OUT_PROMPT_PATH, out_rationale: Path | str = OUT_RATIONALE_PATH,
            max_calls: int = 1) -> tuple[Path, Path]:
    """Ask the model for an improved prompt; write prompt + rationale files."""
    failing, traces = load_failing(Path(run_dir))
    policy = _read(Path(policy_path))
    if prompt_path is None:
        prompt_path = _source_prompt_path(Path(run_dir))
    current_prompt = _read(Path(prompt_path))
    request = build_request(policy, current_prompt, failing, traces)
    if client is None:
        client = MetaClient(max_calls=max_calls, model=model)
    resp = client.responses.create(model=model, input=request)
    new_prompt, rationale = parse_proposal(_response_text(resp))
    targeted = sorted({v["rule"] for r in failing for v in r.get("violations", [])})
    targeted_misses = sorted({m["kind"] for r in failing for m in r.get("misses", [])})
    out_prompt, out_rationale = Path(out_prompt), Path(out_rationale)
    out_prompt.parent.mkdir(parents=True, exist_ok=True)
    out_prompt.write_text(new_prompt + "\n", encoding="utf-8")
    out_rationale.write_text(
        f"# Prompt {out_prompt.stem} rationale\n\n"
        f"Model: {model}\n"
        f"Source run: {Path(run_dir)}\n"
        f"Source prompt: {prompt_path}\n"
        f"Targeted rules: {', '.join(targeted)}\n"
        f"Targeted misses: {', '.join(targeted_misses)}\n"
        f"Failing cases: {', '.join(r['case_id'] for r in failing)}\n\n"
        f"{rationale}\n",
        encoding="utf-8")
    return out_prompt, out_rationale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run directory, e.g. runs/20261026T185535Z")
    ap.add_argument("--policy", default=str(POLICY_PATH))
    ap.add_argument("--prompt", default=None,
                    help="current system prompt (default: the prompt recorded in the run manifest)")
    ap.add_argument("--out-prompt", "--out", dest="out_prompt", default=str(OUT_PROMPT_PATH),
                    help="output prompt file")
    ap.add_argument("--out-rationale", default=None, help="output rationale file (default: <out prompt stem>.rationale.md)")
    ap.add_argument("--model", default=FIXER_MODEL)
    ap.add_argument("--max-calls", type=int, default=1, help="model call budget for the fixer")
    a = ap.parse_args(argv)
    out_prompt = Path(a.out_prompt)
    out_rationale = Path(a.out_rationale) if a.out_rationale else out_prompt.with_name(f"{out_prompt.stem}.rationale.md")
    try:
        out_prompt, out_rationale = fix_run(a.run, model=a.model, policy_path=a.policy, prompt_path=a.prompt,
                                            out_prompt=out_prompt, out_rationale=out_rationale,
                                            max_calls=a.max_calls)
    except (MetaAPIError, RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}")
        return 2
    print(f"prompt: {out_prompt}")
    print(f"rationale: {out_rationale}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
