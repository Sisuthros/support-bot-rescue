"""The support agent under test: a tool loop over the Responses API shape."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.client import DEFAULT_MODEL
from sandbox.authority import FIREWALL_SYSTEM_LINE, FIREWALL_TOOL_SCHEMAS, RefundAuthority
from sandbox.tools import TOOL_SCHEMAS, Sandbox

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "v1.txt"


def _g(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def run_conversation(client: Any, sandbox: Sandbox, turns: list[str], model: str = DEFAULT_MODEL,
                     prompt_path: Path | str = PROMPT_PATH, max_steps: int = 8, firewall: bool = False) -> dict:
    """Play the customer turns against the bot. Returns {"reply", "hit_step_limit"}.

    `reply` joins every assistant message text. Reasoning items are not replayed
    (shortcut: stateless re-send, upgrade if the API needs them echoed back).
    """
    system = Path(prompt_path).read_text(encoding="utf-8").strip()
    if firewall:
        system = f"{system}\n{FIREWALL_SYSTEM_LINE}"
    messages: list[dict] = [{"role": "system", "content": system}]
    executor = RefundAuthority(sandbox) if firewall else sandbox
    tools = FIREWALL_TOOL_SCHEMAS if firewall else TOOL_SCHEMAS
    texts: list[str] = []
    hit_limit = False
    for turn in turns:
        messages.append({"role": "user", "content": turn})
        for step in range(max_steps):
            resp = client.responses.create(model=model, input=messages, tools=tools)
            calls = []
            for item in resp.output:
                kind = _g(item, "type")
                if kind == "message":
                    text = "".join(_g(c, "text", "") for c in _g(item, "content", []) if _g(c, "type") == "output_text")
                    if text:
                        texts.append(text)
                        messages.append({"role": "assistant", "content": text})
                elif kind == "function_call":
                    calls.append(item)
            if not calls:
                break
            for c in calls:
                raw = _g(c, "arguments", "")
                try:
                    args = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    args = {"_unparsed": raw}
                result = executor.call(_g(c, "name"), args)
                messages.append({"type": "function_call", "call_id": _g(c, "call_id"), "name": _g(c, "name"),
                                 "arguments": raw})
                messages.append({"type": "function_call_output", "call_id": _g(c, "call_id"),
                                 "output": json.dumps(result)})
        else:
            hit_limit = True
    return {"reply": "\n".join(texts), "hit_step_limit": hit_limit}
