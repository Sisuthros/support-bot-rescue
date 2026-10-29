"""Model clients with the same `client.responses.create(...)` interface.

MetaClient talks to the Meta Model API (OpenAI-compatible Responses API).
ScriptedClient replays canned outputs for offline tests.
The API key is resolved from the environment or a key file and is never
printed, logged or written anywhere.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3-contributor"


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


def _missing_key_error() -> MetaAPIError:
    return MetaAPIError(
        None,
        "Meta API key not found: set META_API_KEY, or set META_API_KEY_FILE to a file "
        "containing the key, or save the key in ~/.meta-model-api-key",
    )


def _read_key_file(path: Path) -> str | None:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _resolve_api_key(api_key: str | None) -> str:
    if api_key is not None:
        return api_key
    env_key = os.environ.get("META_API_KEY")
    if env_key:
        return env_key
    key_file = os.environ.get("META_API_KEY_FILE")
    if key_file:
        resolved = _read_key_file(Path(key_file))
        if resolved is None:
            raise _missing_key_error()
        return resolved
    resolved = _read_key_file(Path.home() / ".meta-model-api-key")
    if resolved is None:
        raise _missing_key_error()
    return resolved


class MetaClient:
    def __init__(self, max_calls: int = 50, api_key: str | None = None,
                 base_url: str = BASE_URL, model: str = DEFAULT_MODEL) -> None:
        from openai import OpenAI

        api_key = _resolve_api_key(api_key)
        # max_retries=0 so the call budget counts real attempts
        self.raw = OpenAI(base_url=base_url, api_key=api_key, max_retries=0)
        self.model = model
        self.max_calls = max_calls
        self.calls = 0
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        from openai import APIStatusError

        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"model call budget of {self.max_calls} reached")
        self.calls += 1
        kwargs.setdefault("model", self.model)
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
