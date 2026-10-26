"""Model clients with the same `client.responses.create(...)` interface.

MetaClient talks to the Meta Model API (OpenAI-compatible Responses API).
ScriptedClient replays canned outputs for offline tests.
The API key is read from a file and never printed, logged or written anywhere.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3-contributor"
KEY_PATH = Path(r"C:\Users\Ismael\.meta-model-api-key")


class MetaAPIError(RuntimeError):
    def __init__(self, status_code: int | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class PaymentRequired(MetaAPIError):
    """HTTP 402: the Meta account has no payment method."""


class BudgetExceeded(RuntimeError):
    """The per-run model call budget is used up."""


class ScriptExhausted(RuntimeError):
    """ScriptedClient was asked for more responses than the script has."""


class MetaClient:
    def __init__(self, max_calls: int = 50, key_path: Path | str = KEY_PATH, api_key: str | None = None,
                 base_url: str = BASE_URL) -> None:
        from openai import OpenAI

        if api_key is None:
            try:
                api_key = Path(key_path).read_text(encoding="utf-8").strip()
            except OSError as e:
                raise MetaAPIError(None, f"cannot read Meta API key file ({type(e).__name__})") from None
            if not api_key:
                raise MetaAPIError(None, "Meta API key file is empty")
        # max_retries=0 so the call budget counts real attempts
        self.raw = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self.max_calls = max_calls
        self.calls = 0
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        from openai import APIStatusError

        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"model call budget of {self.max_calls} reached")
        self.calls += 1
        try:
            return self.raw.responses.create(**kwargs)
        except APIStatusError as e:
            if e.status_code == 402:
                raise PaymentRequired(
                    402, f"Meta API returned HTTP 402 (payment required): add a payment method to the account. Detail: {e.message}"
                ) from None
            raise MetaAPIError(e.status_code, f"Meta API returned HTTP {e.status_code}: {e.message}") from None


class ScriptedClient:
    """Replays canned model responses.

    `script` is a list of responses; each response is a list of items:
    {"type": "function_call", "name": ..., "arguments": {...}} or {"type": "message", "text": ...}.
    """

    def __init__(self, script: list[list[dict]]) -> None:
        self._script = copy.deepcopy(script)
        self.requests: list[dict] = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(copy.deepcopy(kwargs))
        if not self._script:
            raise ScriptExhausted("scripted client has no more responses")
        n = len(self.requests)
        out = []
        for k, it in enumerate(self._script.pop(0)):
            if it["type"] == "function_call":
                out.append(SimpleNamespace(type="function_call", name=it["name"], call_id=f"call_{n}_{k}",
                                           arguments=json.dumps(it["arguments"])))
            else:
                out.append(SimpleNamespace(type="message", role="assistant", content=[
                    SimpleNamespace(type="output_text", text=it["text"])]))
        return SimpleNamespace(output=out, model="scripted")
