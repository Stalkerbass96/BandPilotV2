"""LLM (AI) layer package."""

from fretpilot.ai.advisor import (
    DEFAULT_STYLE,
    ShadowRewriteAdvisor,
    StyleInferenceResult,
    build_policy,
    extract_features,
    validate_decisions,
)
from fretpilot.ai.crypto import KeyVault, KeyVaultError, get_key_vault
from fretpilot.ai.models import (
    AIProviderError,
    AIProviderIdentity,
    RewriteDecision,
    RewriteRequest,
    RewriteResponse,
    ShadowRewritePolicy,
    TrackFeatures,
)
from fretpilot.ai.providers.base import RewriteAdvisor
from fretpilot.ai.providers.openai_compatible import OpenAICompatibleAdvisor

__all__ = [
    "RewriteAdvisor",
    "OpenAICompatibleAdvisor",
    "AIProviderIdentity",
    "AIProviderError",
    "TrackFeatures",
    "ShadowRewritePolicy",
    "RewriteRequest",
    "RewriteDecision",
    "RewriteResponse",
    "ShadowRewriteAdvisor",
    "StyleInferenceResult",
    "extract_features",
    "build_policy",
    "validate_decisions",
    "DEFAULT_STYLE",
    "KeyVault",
    "KeyVaultError",
    "get_key_vault",
]
