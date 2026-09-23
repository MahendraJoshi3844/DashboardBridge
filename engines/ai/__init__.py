"""The AI layer. Nothing above it imports a vendor (07-ai-engine.md, §26).

`P4.1` is this much: the protocol, the three providers, and the request type
that makes data minimisation structural. The router (`P4.2`) is what decides
whether a model is reached at all, and it is not here yet - so today nothing in
the conversion path imports this package, which is exactly the state the
roadmap describes: with no provider configured, every AI path is absent rather
than degraded.
"""

from engines.ai.provider import LLMProvider, require_loopback
from engines.ai.providers import (
    MockProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)
from engines.ai.types import (
    FieldSchema,
    LLMRequest,
    LLMResponse,
    ProviderUnavailable,
)

__all__ = [
    "FieldSchema",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MockProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderUnavailable",
    "require_loopback",
]
