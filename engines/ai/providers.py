"""The three providers `P4.1` calls for: Ollama, OpenAI-compatible, and Mock.

Each is a thin transport. None of them knows what a proposal is, what a prompt
means, or whether an answer is any good - those belong to the router, and a
provider that could judge its own output would be a provider that could approve
it.
"""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.error
import urllib.request
from dashboardbridge_contracts.enums import PrivacyMode

from engines.ai.provider import require_loopback
from engines.ai.types import LLMResponse, ProviderUnavailable

_PROBE_TIMEOUT_S = 0.4
_GENERATE_TIMEOUT_S = 45.0


class OllamaProvider:
    """A model runtime on this machine.

    The host is validated at construction, not at call time, so an unusable
    provider cannot be built and then held: there is no window in which a
    remote host sits in a configured object waiting to be used.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11434,
        model: str = "llama3.1",
    ) -> None:
        self.host = require_loopback(host)
        self.port = port
        self.model = model

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/api/generate"

    def available(self) -> bool:
        """Is something listening? A socket probe, never a model call."""
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=_PROBE_TIMEOUT_S
            ):
                return True
        except OSError:
            return False

    async def generate(self, prompt: str) -> LLMResponse:
        if not self.available():
            raise ProviderUnavailable(
                f"No model runtime is listening on {self.host}:{self.port}."
            )
        # `urllib` is blocking, so it runs off the event loop rather than
        # stalling it. A dedicated async HTTP client would be a dependency
        # bought for one call.
        return await asyncio.to_thread(self._generate_blocking, prompt)

    def _generate_blocking(self, prompt: str) -> LLMResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            }
        ).encode("utf-8")
        http = urllib.request.Request(
            self.endpoint, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(http, timeout=_GENERATE_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"{self.host}:{self.port} did not answer: {exc}") from exc
        return LLMResponse(text=body.get("response", ""), model=self.model)


class OpenAICompatibleProvider:
    """Any service speaking the OpenAI chat-completions shape.

    Refuses to exist under `LOCAL_ONLY`. The request contract already rejects
    that combination at the API, and this rejects it at the only place a call
    could actually be made - so a future caller that never passes through the
    API inherits the guarantee rather than having to remember it.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        privacy_mode: PrivacyMode = PrivacyMode.STANDARD,
        model: str = "gpt-4o-mini",
    ) -> None:
        if privacy_mode is PrivacyMode.LOCAL_ONLY:
            raise ValueError(
                "local_only forbids a remote provider: workbook content must "
                "not leave this machine. Use a local runtime, or change the "
                "privacy mode deliberately."
            )
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.privacy_mode = privacy_mode
        self.model = model

    def available(self) -> bool:
        """Configured, not reachable.

        Deliberately no network call: `available` is asked before the feature is
        offered, and a remote probe there would put a request on the wire before
        the user has asked for anything.
        """
        return bool(self._api_key and self.base_url)

    async def generate(self, prompt: str) -> LLMResponse:
        if not self.available():
            raise ProviderUnavailable(
                "No API key is configured for the remote provider, so nothing "
                "was sent."
            )
        return await asyncio.to_thread(self._generate_blocking, prompt)

    def _generate_blocking(self, prompt: str) -> LLMResponse:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }
        ).encode("utf-8")
        http = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urllib.request.urlopen(http, timeout=_GENERATE_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"{self.base_url} did not answer: {exc}") from exc
        choices = body.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content", "")
        return LLMResponse(text=text, model=body.get("model", self.model))


class MockProvider:
    """A model that is not a model.

    Not a test convenience: this is what CI uses and what the review flow, the
    schema validation and the human-in-the-loop screens are built against, so a
    model runtime is never needed to develop any of them (07-ai-engine.md).

    It answers identically every time, because a CI run that differs between two
    invocations is a flake nobody can debug. `available=False` is offered for
    the same reason the real ones can be unavailable: "there is no model" is a
    state the product has to render, so it has to be reachable on demand.

    The default answer is `UNKNOWN` - the honest "I cannot help with this" -
    rather than a plausible expression. A mock whose default output looks like a
    real translation is how a fabricated one reaches a screenshot. Callers that
    need a specific answer pass one.
    """

    def __init__(
        self,
        available: bool = True,
        model: str = "mock-1",
        answer: str = "UNKNOWN",
    ) -> None:
        self._available = available
        self.model = model
        self.answer = answer

    def available(self) -> bool:
        return self._available

    async def generate(self, prompt: str) -> LLMResponse:
        if not self._available:
            raise ProviderUnavailable("The mock provider is configured as absent.")
        return LLMResponse(text=self.answer, model=self.model)
