"""Sandbox runner for approved extension checkers.

This file is both an importable client helper and a standalone script.
When run as ``py -3 -I compiler/sandbox_runner.py`` it reads one JSON
object on stdin, executes the checker with a whitelist of builtins, and
writes one JSON object on stdout. Checker code never runs in the parent
process through this module: :func:`run_checker_batch` always spawns the
isolated subprocess.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 5


def _allowed_builtins() -> dict[str, Any]:
    import builtins

    names = ("len", "sum", "min", "max", "abs", "any", "all", "sorted", "str",
             "int", "float", "bool", "isinstance", "dict", "list", "set",
             "tuple", "range", "enumerate", "zip", "round")
    return {name: getattr(builtins, name) for name in names}


class SandboxError(RuntimeError):
    """The sandboxed checker raised, timed out, or returned bad output."""


def _validate_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SandboxError("checker must return a list of findings")
    findings: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"trace_index", "detail"}:
            raise SandboxError("each finding must be an object with only trace_index and detail")
        index = item["trace_index"]
        if index is not None and (isinstance(index, bool) or not isinstance(index, int)):
            raise SandboxError("finding trace_index must be an integer or null")
        if not isinstance(item["detail"], str):
            raise SandboxError("finding detail must be a string")
        findings.append({"trace_index": index, "detail": item["detail"]})
    return findings


def _execute(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("checker_source")
    if not isinstance(source, str) or not source.strip():
        raise SandboxError("checker_source must be a non-empty string")
    calls = payload.get("calls")
    if calls is None:
        calls = [{"params": payload.get("params"), "trace": payload.get("trace"),
                  "state": payload.get("state"), "reply": payload.get("reply")}]
    if not isinstance(calls, list):
        raise SandboxError("calls must be a list")
    namespace: dict[str, Any] = {"__builtins__": _allowed_builtins()}
    try:
        exec(compile(source, "<extension-checker>", "exec"), namespace)
    except Exception as exc:
        raise SandboxError(f"{type(exc).__name__}: {exc}") from None
    check = namespace.get("check")
    if not callable(check):
        raise SandboxError("checker_source must define check(params, trace, state, reply)")
    results: list[list[dict[str, Any]]] = []
    for call in calls:
        if not isinstance(call, dict):
            raise SandboxError("each call must be an object")
        try:
            value = check(call.get("params") or {}, call.get("trace") or [],
                          call.get("state") or {}, call.get("reply") or "")
        except Exception as exc:
            raise SandboxError(f"{type(exc).__name__}: {exc}") from None
        results.append(_validate_findings(value))
    return {"results": results}


def run_checker_batch(checker_source: str, calls: list[dict[str, Any]],
                      timeout: float = TIMEOUT_SECONDS) -> list[list[dict[str, Any]]]:
    """Run ``checker_source`` over ``calls`` in a ``py -3 -I`` subprocess."""
    runner = str(Path(__file__).resolve())
    py_launcher = shutil.which("py")
    if py_launcher:
        command = [py_launcher, "-3", "-I", runner]
    else:
        command = [sys.executable, "-I", runner]
    payload = json.dumps({"checker_source": checker_source, "calls": calls})
    try:
        proc = subprocess.run(command, input=payload, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"sandboxed checker timed out after {timeout} seconds") from None
    except OSError as exc:
        raise SandboxError(f"could not start sandbox subprocess: {exc}") from None
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        raise SandboxError(f"sandbox produced no JSON output: {proc.stderr.strip()[:300]}") from None
    if not isinstance(data, dict):
        raise SandboxError("sandbox produced a non-object response")
    if data.get("error"):
        raise SandboxError(str(data["error"]))
    results = data.get("results")
    if not isinstance(results, list) or len(results) != len(calls):
        raise SandboxError("sandbox returned the wrong number of results")
    return [_validate_findings(result) for result in results]


def run_checker(checker_source: str, params: dict[str, Any], trace: list[dict[str, Any]],
                state: dict[str, Any], reply: str,
                timeout: float = TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    """Run one checker call in the sandbox and return its findings."""
    return run_checker_batch(
        checker_source,
        [{"params": params, "trace": trace, "state": state, "reply": reply}],
        timeout=timeout,
    )[0]


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise SandboxError("input must be a JSON object")
        output = _execute(payload)
    except SandboxError as exc:
        output = {"error": str(exc)}
    except json.JSONDecodeError as exc:
        output = {"error": f"invalid JSON input: {exc}"}
    except Exception as exc:
        output = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(output) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
