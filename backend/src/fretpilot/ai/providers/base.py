"""RewriteAdvisor protocol — the LLM abstraction layer.

The advisor only produces *judgments* (style labels, rewrite suggestions).
It never touches MIDI data. Concrete implementations (e.g.
OpenAICompatibleAdvisor) make actual HTTP calls; the protocol enables
mocking in tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fretpilot.ai.models import (
    AIProviderIdentity,
    RewriteRequest,
    RewriteResponse,
    TrackFeatures,
)


@runtime_checkable
class RewriteAdvisor(Protocol):
    """Protocol for LLM-based decision advisors.

    Implementations must be safe to call: network errors should raise
    AIProviderError so the caller can fall back to degraded mode.
    """

    identity: AIProviderIdentity

    def infer_style(self, features: TrackFeatures) -> str:
        """Infer a style label (Funk/Rock/Metal/Pop/...) from track features."""
        ...

    def propose_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        """Propose note rewrite decisions (delete/transpose) for validation."""
        ...


__all__ = ["RewriteAdvisor"]
