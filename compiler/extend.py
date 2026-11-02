"""Propose, gate, approve, and apply new DSL primitives from uncovered policy sentences.

The model (muse-wonder-1.0) may *propose* a primitive; it never judges.
Plain code gates every proposal (shape, AST whitelist, sandboxed self-test,
informational replay), a named person approves it with the ``approve``
command, and only approved, sha256-pinned checkers are ever run by
:mod:`compiler.spec_judge` (through :mod:`compiler.sandbox_runner`).

Usage:
    py -3 -m compiler.extend propose --policy P --spec S [--run DIR] [--budget N]
    py -3 -m compiler.extend list [--store X]
    py -3 -m compiler.extend approve FILE --by NAME
    py -3 -m compiler.extend apply --spec S --proposals DIR --out O
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.client import MetaClient  # noqa: E402
from compiler.compile_policy import COMPILER_MODEL, _response_text  # noqa: E402
from compiler.dsl import PRIMITIVES, SpecError, checker_sha256, validate_spec  # noqa: E402
from compiler.dsl import _check_value  # noqa: E402
from compiler.sandbox_runner import SandboxError, run_checker, run_checker_batch  # noqa: E402

__all__ = [
    "ProposalError", "build_proposal_request", "validate_checker_ast",
    "gate_proposal", "propose", "approve_proposal", "list_proposals",
    "load_approved_proposals", "apply_proposals", "checker_sha256", "main",
]

PROPOSALS_ROOT = Path(__file__).resolve().parent / "proposals"
EXTEND_MODEL = COMPILER_MODEL
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TYPE_TAGS = ("string", "positive_int", "positive_number", "string_list")
_BANNED_NODES = (
    ast.Import, ast.ImportFrom, ast.While, ast.Lambda, ast.ClassDef,
    ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.Global,
    ast.Nonlocal, ast.With, ast.AsyncWith, ast.Try, ast.Raise, ast.Delete,
)
_BANNED_NAMES = {
    "eval", "exec", "compile", "open", "__import__", "getattr", "setattr",
    "delattr", "globals", "locals", "vars", "input", "breakpoint", "exit",
    "quit", "help", "memoryview", "type", "object", "super",
}
_ALLOWED_BUILTINS = ("len, sum, min, max, abs, any, all, sorted, str, int, "
                     "float, bool, isinstance, dict, list, set, tuple, range, "
                     "enumerate, zip, round")


class ProposalError(ValueError):
    """A proposal is malformed, fails the gate, or cannot be approved/applied."""


def _norm_ws(text: Any) -> str:
    return " ".join(str(text).split())


def build_proposal_request(policy_text: str, uncovered_quote: str, uncovered_reason: str,
                           world_sample: Any, spec_dict: dict[str, Any],
                           retry_error: str | None = None) -> str:
    """Build the muse-wonder-1.0 prompt asking for one new primitive, or a decline."""
    request = (
        "You propose a NEW primitive for a closed, typed judging DSL. Deterministic code "
        "will gate your proposal and a named human must approve it before it can judge "
        "anything; you are not judging any conversation yourself.\n"
        "Reply with ONLY a JSON object (no markdown fences, no commentary), in exactly one "
        "of these two shapes:\n"
        "1) Proposal: {\"primitive\": snake_case name not colliding with the built-in "
        "primitives listed below, \"description\": string, \"params\": {name: type tag, one "
        "of string, positive_int, positive_number, string_list}, \"checker_source\": "
        "\"def check(params, trace, state, reply): ...\" returning a list of "
        "{\"trace_index\": int|null, \"detail\": string}, \"rule\": {\"quote\": the verbatim "
        "uncovered quote below, \"params\": {...values matching your params schema...}}, "
        "\"examples\": {\"violating\": [at least 2 {\"trace\", \"state\", \"reply\"}], "
        "\"clean\": [at least 2 {\"trace\", \"state\", \"reply\"}]}, "
        "\"required_world_fields\": [string]}\n"
        "2) Decline: {\"decline\": reason}. Use this when the sentence is an obligation the "
        "trace cannot show, or when it needs data the world does not have. Declining "
        "honestly is a valid outcome; do not invent world fields, tools, or trace data.\n\n"
        "Checker constraints (a plain-code AST gate enforces these): checker_source must "
        "contain exactly one top-level function `def check(params, trace, state, reply):` "
        "and nothing else at top level. No imports, while loops, lambdas, classes, async, "
        "await, yield, global, nonlocal, with, try, raise, or delete. No attribute whose "
        "name starts with `_`. No eval, exec, compile, open, __import__, getattr, setattr, "
        "delattr, globals, locals, vars, input, breakpoint, exit, quit, help, memoryview, "
        f"type, object, or super. Only these builtins are available: {_ALLOWED_BUILTINS}. "
        "The checker must be deterministic and return findings only for violations of the "
        "quoted sentence.\n\n"
        "Shapes the checker receives (exactly as compiler/spec_judge.py and "
        "judge_stored_trace use them):\n"
        "- trace: a list of tool-call dicts, each {\"name\": tool name string, \"args\": "
        "dict of arguments, \"result\": dict where result[\"ok\"] is True on success}; "
        "stored traces may also carry an \"index\" int per call. Example tools: "
        "lookup_order(order_id, email) with result.order on success, issue_refund(order_id, "
        "amount, reason), update_account(customer_id, field, value), escalate_to_human(reason).\n"
        "- state: a dict {\"today\": \"YYYY-MM-DD\" date string, \"orders\": dict keyed by "
        "order_id whose values are order entities, \"customers\": dict keyed by customer_id, "
        "\"refunds\": list, \"escalations\": list, \"account_changes\": list} plus any other "
        "entity collections the world provides. judge_stored_trace builds this from the "
        "stored trace payload's final_state (today/orders from the world, plus refunds, "
        "escalations and account_changes when present) and the world itself.\n"
        "- reply: the bot's final reply as a single string (possibly empty).\n"
        "- params: the dict from your rule, type-checked against your params schema.\n\n"
        f"Built-in primitives you must not collide with or reuse: {json.dumps(PRIMITIVES, indent=2)}\n\n"
        f"Uncovered sentence (copy this verbatim as rule.quote): {uncovered_quote}\n"
        f"Why the compiler left it uncovered: {uncovered_reason}\n\n"
        f"--- WORLD SAMPLE (from the run/world data; required_world_fields may only name "
        f"data that exists here or in the shapes above) ---\n"
        f"{json.dumps(world_sample, indent=2, default=str)}\n\n"
        f"--- EXISTING SPEC ---\n{json.dumps(spec_dict, indent=2, default=str)}\n\n"
        f"--- POLICY ---\n{policy_text}\n"
    )
    if retry_error:
        request += (
            "\nYour previous reply was rejected by the deterministic proposal gate with "
            f"this error:\n{retry_error}\nReply again with ONLY the corrected JSON object "
            "(or a decline object).\n"
        )
    return request


def validate_checker_ast(checker_source: str) -> None:
    """Enforce the AST whitelist on ``checker_source``; raise ProposalError."""
    if not isinstance(checker_source, str) or not checker_source.strip():
        raise ProposalError("checker_source must be a non-empty string")
    try:
        tree = ast.parse(checker_source)
    except SyntaxError as exc:
        raise ProposalError(f"checker_source is not valid Python: {exc}") from None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ProposalError("checker_source must contain exactly one top-level function named check")
    fn = tree.body[0]
    if fn.name != "check":
        raise ProposalError("the single top-level function must be named check")
    args = fn.args
    arg_names = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    if arg_names != ["params", "trace", "state", "reply"] or args.vararg or args.kwarg \
            or args.kwonlyargs or args.defaults or args.kw_defaults:
        raise ProposalError("check must take exactly (params, trace, state, reply)")
    if fn.decorator_list:
        raise ProposalError("check must not have decorators")
    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODES):
            raise ProposalError(f"checker uses banned construct: {type(node).__name__}")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ProposalError("checker must contain exactly one function definition")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _BANNED_NAMES):
            raise ProposalError(f"checker uses banned attribute: {node.attr}")
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            raise ProposalError(f"checker uses banned name: {node.id}")


def _step(name: str, ok: bool, message: str, **extra: Any) -> dict[str, Any]:
    step: dict[str, Any] = {"step": name, "ok": bool(ok), "message": message}
    step.update(extra)
    return step


def _is_decline(candidate: Any) -> bool:
    return isinstance(candidate, dict) and "decline" in candidate

def _check_example_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ProposalError(f"examples.{label} must contain at least 2 examples")
    for item in value:
        if not isinstance(item, dict) or set(item) != {"trace", "state", "reply"}:
            raise ProposalError(f"each examples.{label} item must have only trace, state and reply")
        if not isinstance(item["trace"], list) or any(not isinstance(c, dict) for c in item["trace"]):
            raise ProposalError(f"examples.{label} trace must be a list of tool-call objects")
        if not isinstance(item["state"], dict):
            raise ProposalError(f"examples.{label} state must be an object")
        if not isinstance(item["reply"], str):
            raise ProposalError(f"examples.{label} reply must be a string")
    return value


def _check_proposal_shape(candidate: Any, policy_text: str, expected_quote: str | None) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ProposalError("proposal must be a JSON object")
    required = {"primitive", "description", "params", "checker_source", "rule", "examples",
                "required_world_fields"}
    if set(candidate) != required:
        raise ProposalError(f"proposal must have exactly the keys {sorted(required)}, got {sorted(candidate)}")
    primitive = candidate["primitive"]
    if not isinstance(primitive, str) or not _SNAKE_RE.match(primitive):
        raise ProposalError(f"primitive must be a snake_case name: {primitive!r}")
    if primitive in PRIMITIVES:
        raise ProposalError(f"primitive {primitive!r} collides with a built-in primitive")
    if not isinstance(candidate["description"], str) or not candidate["description"].strip():
        raise ProposalError("description must be a non-empty string")
    schema = candidate["params"]
    if not isinstance(schema, dict) or any(
            not isinstance(k, str) or not k or v not in _TYPE_TAGS for k, v in schema.items()):
        raise ProposalError("params must map names to one of string, positive_int, positive_number, string_list")
    if not isinstance(candidate["checker_source"], str) or not candidate["checker_source"].strip():
        raise ProposalError("checker_source must be a non-empty string")
    rule = candidate["rule"]
    if not isinstance(rule, dict) or set(rule) != {"quote", "params"}:
        raise ProposalError("rule must be an object with only quote and params")
    quote = rule["quote"]
    if not isinstance(quote, str) or not quote.strip():
        raise ProposalError("rule.quote must be a non-empty string")
    if _norm_ws(quote) not in _norm_ws(policy_text):
        raise ProposalError("rule.quote is not verbatim in the policy text")
    if expected_quote is not None and _norm_ws(quote) != _norm_ws(expected_quote):
        raise ProposalError("rule.quote must be the verbatim uncovered quote")
    params = rule["params"]
    if not isinstance(params, dict) or set(params) != set(schema):
        raise ProposalError(f"rule.params must be exactly {sorted(schema)}")
    for name, tag in schema.items():
        try:
            _check_value("proposal", name, params[name], tag)
        except SpecError as exc:
            raise ProposalError(str(exc)) from None
    examples = candidate["examples"]
    if not isinstance(examples, dict) or set(examples) != {"violating", "clean"}:
        raise ProposalError("examples must be an object with only violating and clean")
    _check_example_list(examples["violating"], "violating")
    _check_example_list(examples["clean"], "clean")
    fields = candidate["required_world_fields"]
    if not isinstance(fields, list) or any(not isinstance(f, str) or not f for f in fields):
        raise ProposalError("required_world_fields must be a list of non-empty strings")
    return candidate


def _replay_calls(candidate: dict[str, Any], run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    traces_dir = run_dir / "traces"
    files = sorted(traces_dir.rglob("*.json")) if traces_dir.is_dir() else []
    world: dict[str, Any] = {}
    world_path = run_dir / "world.json"
    if world_path.is_file():
        try:
            from sandbox.tools import load_world
            world = load_world(world_path)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            raw = json.loads(world_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                world = dict(raw)
                if isinstance(world.get("orders"), list):
                    world["orders"] = {str(o.get("order_id")): o for o in world["orders"]
                                        if isinstance(o, dict)}
    calls: list[dict[str, Any]] = []
    used_files: list[str] = []
    for file in files:
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("trace"), list):
            continue
        final = payload.get("final_state") or {}
        state: dict[str, Any] = {}
        if world:
            state = {"today": world.get("today"), "orders": world.get("orders")}
            state.update({k: final[k] for k in ("refunds", "escalations", "account_changes") if k in final})
            for key, value in world.items():
                state.setdefault(key, value)
        calls.append({"params": candidate["rule"]["params"], "trace": payload.get("trace") or [],
                      "state": state, "reply": payload.get("reply") or ""})
        used_files.append(str(file.relative_to(run_dir)))
    info = {"run": str(run_dir), "traces": len(calls), "files": used_files}
    return calls, info


def gate_proposal(candidate: Any, policy_text: str, run_dir: Path | str | None = None,
                  expected_quote: str | None = None) -> dict[str, Any]:
    """Run the plain-code gate; return status, per-step results, and the proposal."""
    steps: list[dict[str, Any]] = []

    def failed(step: dict[str, Any]) -> dict[str, Any]:
        steps.append(step)
        return {"status": "gate_failed", "gate": steps, "gate_results": steps,
                "gate_failed_step": step["step"], "message": step["message"],
                "proposal": candidate if isinstance(candidate, dict) else None}

    if _is_decline(candidate):
        if set(candidate) != {"decline"} or not isinstance(candidate["decline"], str) \
                or not candidate["decline"].strip():
            return failed(_step("json_shape", False, "decline must be an object with only a non-empty decline reason"))
        steps.append(_step("json_shape", True, "decline object is well-formed"))
        return {"status": "declined", "gate": steps, "gate_results": steps,
                "gate_failed_step": None, "message": candidate["decline"], "proposal": candidate}

    try:
        _check_proposal_shape(candidate, policy_text, expected_quote)
    except ProposalError as exc:
        return failed(_step("json_shape", False, str(exc)))
    steps.append(_step("json_shape", True, "JSON shape, types, param schema and verbatim quote are valid"))

    try:
        validate_checker_ast(candidate["checker_source"])
    except ProposalError as exc:
        return failed(_step("ast_whitelist", False, str(exc)))
    steps.append(_step("ast_whitelist", True, "checker_source passes the AST whitelist"))

    examples = candidate["examples"]
    first = examples["violating"][0]
    try:
        run_checker(candidate["checker_source"], candidate["rule"]["params"],
                    first["trace"], first["state"], first["reply"])
    except (SandboxError, TimeoutError) as exc:
        return failed(_step("sandbox_execution", False, f"sandboxed checker failed: {exc}"))
    steps.append(_step("sandbox_execution", True, "checker executed in the py -3 -I sandbox subprocess"))

    calls = [{"params": candidate["rule"]["params"], "trace": e["trace"],
              "state": e["state"], "reply": e["reply"]}
             for e in examples["violating"] + examples["clean"]]
    try:
        results = run_checker_batch(candidate["checker_source"], calls)
    except (SandboxError, TimeoutError) as exc:
        return failed(_step("self_test", False, f"sandboxed checker failed during self-test: {exc}"))
    n_violating = len(examples["violating"])
    violating_counts = [len(r) for r in results[:n_violating]]
    clean_counts = [len(r) for r in results[n_violating:]]
    if any(count < 1 for count in violating_counts) or any(count != 0 for count in clean_counts):
        return failed(_step("self_test", False,
                            f"self-test failed: violating findings {violating_counts}, clean findings {clean_counts}"))
    steps.append(_step("self_test", True, "every violating example gives >=1 finding and every clean example 0",
                       violating_findings=violating_counts, clean_findings=clean_counts))

    replay_info: dict[str, Any] = {"traces": 0, "findings": 0}
    if run_dir is None:
        steps.append(_step("replay", True, "no run directory supplied; replay skipped",
                           informational=True, traces=0, findings=0))
    else:
        replay_calls, replay_info = _replay_calls(candidate, Path(run_dir))
        replay_info = {**replay_info, "findings": 0}
        if not replay_calls:
            steps.append(_step("replay", True, "no stored traces found to replay",
                               informational=True, **replay_info))
        else:
            try:
                replay_results = run_checker_batch(candidate["checker_source"], replay_calls)
                replay_info["findings"] = sum(len(r) for r in replay_results)
                steps.append(_step("replay", True,
                                   f"replayed over {len(replay_calls)} stored traces without raising",
                                   informational=True, **replay_info))
            except (SandboxError, TimeoutError) as exc:
                replay_info["error"] = str(exc)
                steps.append(_step("replay", False,
                                   f"replay failed (informational, not a gate): {exc}",
                                   informational=True, **replay_info))
    return {"status": "proposed", "gate": steps, "gate_results": steps,
            "gate_failed_step": None, "message": "all gates passed",
            "proposal": candidate, "replay": replay_info}
def _parse_response_text(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[A-Za-z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _response_id(resp: Any) -> Any:
    return resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)


def _store_name(policy_path: Path, spec_path: Path) -> str:
    if policy_path.name == "policy.md" and policy_path.parent.name:
        return policy_path.parent.name
    if policy_path.stem:
        return policy_path.stem
    return spec_path.stem.split(".")[0]


def propose(policy_path: Path | str, spec_path: Path | str, run_dir: Path | str | None = None,
            budget: int = 8, client: Any = None, model: str = EXTEND_MODEL,
            proposals_root: Path | str | None = None, store: str | None = None) -> list[dict[str, Any]]:
    """One Wonder call per uncovered sentence (plus at most one gate-error retry each).

    Persists every outcome under ``compiler/proposals/<store>/`` and returns
    the records. Nothing is ever approved here.
    """
    policy_path, spec_path = Path(policy_path), Path(spec_path)
    policy_bytes = policy_path.read_bytes()
    policy_text = policy_bytes.decode("utf-8")
    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    spec_dict = json.loads(spec_path.read_text(encoding="utf-8"))
    validate_spec(spec_dict, policy_text=policy_text)
    store_name = store or _store_name(policy_path, spec_path)
    out_dir = Path(proposals_root) / store_name if proposals_root else PROPOSALS_ROOT / store_name
    out_dir.mkdir(parents=True, exist_ok=True)
    world_sample: Any = {}
    if run_dir is not None and (Path(run_dir) / "world.json").is_file():
        world_sample = json.loads((Path(run_dir) / "world.json").read_text(encoding="utf-8"))
    if client is None:
        client = MetaClient(max_calls=budget, model=model)
    calls_used = 0
    records: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, uncovered in enumerate(spec_dict.get("uncovered") or [], start=1):
        if calls_used >= budget:
            break
        quote = uncovered.get("quote", "") if isinstance(uncovered, dict) else ""
        reason = uncovered.get("reason", "") if isinstance(uncovered, dict) else ""
        attempts: list[dict[str, Any]] = []
        gate_result: dict[str, Any] | None = None
        candidate: Any = None
        last_request, last_raw, last_id, last_model = "", "", None, model
        retry_error: str | None = None
        for _attempt in range(2):
            if calls_used >= budget:
                break
            request = build_proposal_request(policy_text, quote, reason, world_sample,
                                             spec_dict, retry_error=retry_error)
            resp = client.responses.create(model=model, input=request)
            calls_used += 1
            last_request = request
            last_raw = _response_text(resp)
            last_id = _response_id(resp)
            resp_model = resp.get("model") if isinstance(resp, dict) else getattr(resp, "model", None)
            if isinstance(resp_model, str) and resp_model:
                last_model = resp_model
            try:
                candidate = _parse_response_text(last_raw)
            except json.JSONDecodeError as exc:
                gate_result = {"status": "gate_failed",
                               "gate": [_step("json_shape", False, f"model reply is not JSON: {exc}")],
                               "gate_failed_step": "json_shape",
                               "message": f"model reply is not JSON: {exc}", "proposal": None}
                gate_result["gate_results"] = gate_result["gate"]
            else:
                gate_result = gate_proposal(candidate, policy_text, run_dir=run_dir,
                                            expected_quote=quote)
            attempts.append({"request": request, "raw_response": last_raw,
                             "response_id": last_id, "status": gate_result["status"],
                             "gate": gate_result["gate"]})
            if gate_result["status"] != "gate_failed":
                break
            retry_error = f"{gate_result.get('gate_failed_step')}: {gate_result.get('message')}"
        assert gate_result is not None
        record: dict[str, Any] = {
            "store": store_name, "model": last_model, "response_id": last_id,
            "policy_sha256": policy_sha, "quote": quote, "reason": reason,
            "request": last_request, "raw_response": last_raw,
            "gate": gate_result["gate"], "gate_results": gate_result["gate"],
            "gate_failed_step": gate_result.get("gate_failed_step"),
            "status": gate_result["status"], "attempts": attempts, "calls_used": calls_used,
        }
        if isinstance(candidate, dict):
            for key in ("primitive", "description", "params", "checker_source", "rule",
                        "examples", "required_world_fields", "decline"):
                if key in candidate:
                    record[key] = candidate[key]
        if "replay" in gate_result:
            record["replay"] = gate_result["replay"]
        if record["status"] == "declined":
            filename = f"declined-{index}.json"
        else:
            primitive = record.get("primitive")
            if isinstance(primitive, str) and _SNAKE_RE.match(primitive) and primitive not in PRIMITIVES:
                filename = f"{primitive}.json"
            else:
                filename = f"gate_failed-{index}.json"
            if filename in used_names:
                filename = f"{Path(filename).stem}-{index}.json"
        used_names.add(filename)
        record["proposal_file"] = filename
        (out_dir / filename).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        records.append(record)
    return records


def approve_proposal(proposal_path: Path | str, by: str) -> dict[str, Any]:
    """Approve a ``proposed`` record in place; refuse every other status."""
    if not isinstance(by, str) or not by.strip():
        raise ProposalError("approve requires a non-empty approver name (--by NAME)")
    path = Path(proposal_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("status") != "proposed":
        status = record.get("status") if isinstance(record, dict) else type(record).__name__
        raise ProposalError(f"refusing to approve {path}: status is {status!r}, only 'proposed' can be approved")
    source = record.get("checker_source")
    if not isinstance(source, str) or not source.strip():
        raise ProposalError(f"refusing to approve {path}: missing checker_source")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record["status"] = "approved"
    record["approval"] = {"by": by.strip(), "timestamp": timestamp,
                          "checker_sha256": checker_sha256(source)}
    record["approved_by"] = by.strip()
    record["approved_at"] = timestamp
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _resolve_store_dir(store: Any = None) -> Path:
    if store is None:
        return PROPOSALS_ROOT
    path = Path(store)
    if path.is_dir():
        return path
    return PROPOSALS_ROOT / str(store)


def list_proposals(store: Any = None) -> list[dict[str, Any]]:
    """List persisted proposal records (each with a ``_path``), sorted by path."""
    base = _resolve_store_dir(store)
    if not base.is_dir():
        return []
    files = sorted(base.rglob("*.json")) if base == PROPOSALS_ROOT else sorted(base.glob("*.json"))
    out: list[dict[str, Any]] = []
    for file in files:
        try:
            record = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                record = {"status": "unreadable"}
        except (OSError, json.JSONDecodeError) as exc:
            record = {"status": "unreadable", "error": str(exc)}
        record = dict(record)
        record["_path"] = str(file)
        out.append(record)
    return out


def load_approved_proposals(proposals_dir: Path | str) -> list[dict[str, Any]]:
    """Load approved records from a proposals directory, verifying approval sha256."""
    path = Path(proposals_dir)
    files = [path] if path.is_file() else sorted(path.glob("*.json")) if path.is_dir() else []
    approved: list[dict[str, Any]] = []
    for file in files:
        record = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("status") != "approved":
            continue
        approval = record.get("approval") or {}
        source = record.get("checker_source") or ""
        if approval.get("checker_sha256") != checker_sha256(source):
            raise ProposalError(
                f"approved checker in {file} no longer matches its approval sha256; refusing to load it")
        approved.append(record)
    return approved
def _next_rule_id(rules: list[dict[str, Any]]) -> tuple[str, int]:
    prefix, maximum = "C", 0
    for rule in rules:
        match = re.match(r"^([A-Za-z]+)(\d+)$", str(rule.get("id", "")))
        if match:
            maximum = max(maximum, int(match.group(2)))
    return prefix, maximum + 1


def apply_proposals(spec_dict: dict[str, Any], proposals: Any) -> dict[str, Any]:
    """Return the spec plus each approved proposal's rule, moved out of uncovered."""
    if isinstance(proposals, (str, Path)):
        approved = load_approved_proposals(proposals)
    elif isinstance(proposals, dict):
        approved = [proposals] if proposals.get("status") == "approved" else []
    else:
        approved = [r for r in proposals if isinstance(r, dict) and r.get("status") == "approved"]
    for record in approved:
        approval = record.get("approval") or {}
        if approval.get("checker_sha256") != checker_sha256(record.get("checker_source") or ""):
            raise ProposalError("approved checker sha256 no longer matches its approval; refusing to apply")
    result = json.loads(json.dumps(spec_dict))
    rules: list[dict[str, Any]] = result.setdefault("rules", [])
    prefix, next_number = _next_rule_id(rules)
    provenance = dict(result.get("provenance") or {})
    extension_entries = list(provenance.get("extensions") or [])
    known = {(e.get("name"), e.get("checker_sha256")) for e in extension_entries if isinstance(e, dict)}
    for record in approved:
        primitive = record.get("primitive") or record.get("name")
        rule = record.get("rule") or {}
        quote, params = rule.get("quote"), rule.get("params")
        if not isinstance(primitive, str) or not isinstance(quote, str) or not isinstance(params, dict):
            raise ProposalError("approved proposal is missing primitive, rule.quote, or rule.params")
        if not any(r.get("primitive") == primitive and r.get("quote") == quote for r in rules):
            rules.append({"id": f"{prefix}{next_number}", "primitive": primitive,
                          "quote": quote, "params": params})
            next_number += 1
        if isinstance(result.get("uncovered"), list):
            result["uncovered"] = [item for item in result["uncovered"]
                                   if _norm_ws(item.get("quote", "")) != _norm_ws(quote)]
        entry = {"name": primitive, "checker_sha256": checker_sha256(record["checker_source"])}
        if (entry["name"], entry["checker_sha256"]) not in known:
            extension_entries.append(entry)
            known.add((entry["name"], entry["checker_sha256"]))
    if extension_entries:
        provenance["extensions"] = extension_entries
        result["provenance"] = provenance
    if result.get("uncovered") == []:
        result.pop("uncovered", None)
    validate_spec(result, extensions=approved)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="compiler.extend")
    sub = parser.add_subparsers(dest="command", required=True)
    propose_parser = sub.add_parser("propose")
    propose_parser.add_argument("--policy", required=True)
    propose_parser.add_argument("--spec", required=True)
    propose_parser.add_argument("--run", default=None)
    propose_parser.add_argument("--budget", type=int, default=8)
    propose_parser.add_argument("--store", default=None)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--store", default=None)
    approve_parser = sub.add_parser("approve")
    approve_parser.add_argument("file")
    approve_parser.add_argument("--by", required=True)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--spec", required=True)
    apply_parser.add_argument("--proposals", required=True)
    apply_parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "propose":
            records = propose(args.policy, args.spec, run_dir=args.run,
                              budget=args.budget, store=args.store)
            total_calls = records[-1]["calls_used"] if records else 0
            for record in records:
                print(f"{record['status']}: {record.get('quote', '')} "
                      f"-> compiler/proposals/{record['store']}/{record.get('proposal_file')} "
                      f"response_id={record.get('response_id')}")
            print(f"wonder calls: {total_calls} of budget {args.budget}")
            return 0
        if args.command == "list":
            for record in list_proposals(args.store):
                print(f"{record['_path']}: status={record.get('status')} "
                      f"primitive={record.get('primitive', '-')} quote={record.get('quote', '')}")
            return 0
        if args.command == "approve":
            record = approve_proposal(args.file, args.by)
            print(f"approved: {args.file} by={record['approval']['by']} "
                  f"checker_sha256={record['approval']['checker_sha256']}")
            return 0
        if args.command == "apply":
            spec_dict = json.loads(Path(args.spec).read_text(encoding="utf-8"))
            result = apply_proposals(spec_dict, args.proposals)
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"spec: {out} rules={len(result['rules'])}")
            return 0
    except (ProposalError, SpecError, OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
