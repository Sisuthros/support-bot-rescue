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


class Conversation:
    """One bot conversation: keeps message history across customer turns."""

    def __init__(self, client: Any, sandbox: Sandbox, prompt_path: Path | str = PROMPT_PATH,
                 model: str = DEFAULT_MODEL, max_steps: int = 8, firewall: bool = False) -> None:
        self.client = client
        self.sandbox = sandbox
        self.prompt_path = prompt_path
        self.model = model
        self.max_steps = max_steps
        self.firewall = firewall
        system = f"{Path(prompt_path).read_text(encoding='utf-8').strip()}\nToday's date: {sandbox.today}"
        if firewall:
            system = f"{system}\n{FIREWALL_SYSTEM_LINE}"
        self.system = system
        self.messages: list[dict] = [{"role": "system", "content": system}]
        self.executor = RefundAuthority(sandbox) if firewall else sandbox
        self.tools = FIREWALL_TOOL_SCHEMAS if firewall else TOOL_SCHEMAS
        self.texts: list[str] = []
        self.hit_step_limit = False

    def say(self, turn: str) -> str:
        """Run the tool loop for one customer turn; return that turn's reply text."""
        self.messages.append({"role": "user", "content": turn})
        turn_texts: list[str] = []
        for step in range(self.max_steps):
            resp = self.client.responses.create(model=self.model, input=self.messages, tools=self.tools)
            calls = []
            for item in resp.output:
                kind = _g(item, "type")
                if kind == "message":
                    text = "".join(_g(c, "text", "") for c in _g(item, "content", []) if _g(c, "type") == "output_text")
                    if text:
                        turn_texts.append(text)
                        self.texts.append(text)
                        self.messages.append({"role": "assistant", "content": text})
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
                result = self.executor.call(_g(c, "name"), args)
                self.messages.append({"type": "function_call", "call_id": _g(c, "call_id"), "name": _g(c, "name"),
                                      "arguments": raw})
                self.messages.append({"type": "function_call_output", "call_id": _g(c, "call_id"),
                                      "output": json.dumps(result)})
        else:
            self.hit_step_limit = True
        return "\n".join(turn_texts)


def run_conversation(client: Any, sandbox: Sandbox, turns: list[str], model: str = DEFAULT_MODEL,
                     prompt_path: Path | str = PROMPT_PATH, max_steps: int = 8, firewall: bool = False) -> dict:
    """Play the customer turns against the bot. Returns {"reply", "hit_step_limit"}.

    `reply` joins every assistant message text. Reasoning items are not replayed
    (shortcut: stateless re-send, upgrade if the API needs them echoed back).
    """
    conversation = Conversation(client, sandbox, prompt_path=prompt_path, model=model,
                                max_steps=max_steps, firewall=firewall)
    for turn in turns:
        conversation.say(turn)
    return {"reply": "\n".join(conversation.texts), "hit_step_limit": conversation.hit_step_limit}
