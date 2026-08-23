"""OpenAI-compatible LLM adapter.

Works with any OpenAI-compatible chat completions API (OpenAI, DeepSeek,
most国产 LLM providers). Uses httpx for HTTP calls with timeout control.
The adapter only produces *decisions* — it never touches MIDI data.
"""

from __future__ import annotations

import json
import logging

import httpx

from fretpilot.ai.models import (
    AIProviderError,
    AIProviderIdentity,
    RewriteDecision,
    RewriteRequest,
    RewriteResponse,
    TrackFeatures,
)
from fretpilot.ai.url_security import UnsafeProviderUrl, validate_provider_base_url

logger = logging.getLogger("fretpilot.ai.providers.openai")

_STYLE_SYSTEM_PROMPT = (
    "You are a music style classifier for guitar MIDI. "
    "Given track features, respond with exactly one style label from: "
    "funk, rock, metal, pop. "
    "Choose the single closest match. Respond with only the label, lowercase, "
    "with no other text, punctuation, or explanation."
)

_REWRITE_SYSTEM_PROMPT = (
    "You are a guitar MIDI repair advisor. Given note summaries, tuning info, and a policy, "
    "propose minimal rewrite decisions. For out-of-range notes, prefer transposing to the nearest "
    "in-range pitch rather than deleting. Only delete notes that are clearly noise (very short, "
    "velocity 0, or isolated artifacts). Respect the max_deletions and max_transpositions limits. "
    "Respond with ONLY a JSON object, no markdown fences, no surrounding text: "
    '{"decisions": [{"index": int, "operation": "delete"|"transpose", '
    '"pitch": int|null, "reason": str}]}. Only suggest changes you are confident about.'
)

# The knowledge base (KB1/KB2) only ships priors for these four styles.  A
# label outside this set silently falls back to default priors, so we constrain
# the LLM to this canonical set.
_VALID_STYLES = frozenset({"funk", "rock", "metal", "pop"})

# Map common LLM outputs to the nearest supported style so a slightly-off
# label (e.g. "classical", "punk") still lands on real KB priors.
_STYLE_ALIASES = {
    "classical": "pop",
    "fingerstyle": "pop",
    "acoustic": "pop",
    "indie": "pop",
    "punk": "rock",
    "hardrock": "rock",
    "hard_rock": "rock",
    "thrash": "metal",
    "heavy": "metal",
    "death": "metal",
    "djent": "metal",
    "fusion": "funk",
    "rnb": "funk",
    "soul": "funk",
    "groove": "funk",
    "blues": "rock",
    "country": "pop",
    "jazz": "pop",
}


class OpenAICompatibleAdvisor:
    """LLM advisor using the OpenAI chat completions API format."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = validate_provider_base_url(base_url)
        self._timeout = timeout
        self.identity = AIProviderIdentity(
            provider="openai_compatible",
            model=model,
            base_url=self._base_url,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _chat(self, system_prompt: str, user_content: str) -> str:
        """Make a chat completion request and return the assistant message."""
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            # Reasoning models (e.g. deepseek-v4-pro) spend a large portion of
            # max_tokens on internal reasoning; a low cap leaves an empty
            # `content`.  Give enough headroom for both reasoning + answer.
            "max_tokens": 4096,
        }
        try:
            validate_provider_base_url(self._base_url, resolve_dns=True)
            with httpx.Client(follow_redirects=False, trust_env=False) as client:
                response = client.post(
                    url, json=payload, headers=self._headers(), timeout=self._timeout
                )
            response.raise_for_status()
        except (httpx.HTTPError, UnsafeProviderUrl) as exc:
            raise AIProviderError(f"LLM request failed: {exc}") from exc

        try:
            data = response.json()
            message = data["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("LLM returned an invalid response payload") from exc
        # Some providers return the answer in `content`; reasoning models may
        # keep it there too (with the thinking in `reasoning_content`).  If
        # `content` is empty/missing, fall back to `reasoning_content` so we
        # never silently return an empty string.
        return (message.get("content") or message.get("reasoning_content") or "").strip()

    def infer_style(self, features: TrackFeatures) -> str:
        """Infer a style label from track features via LLM.

        Robust to sentence responses: scans for the first supported-style word
        rather than assuming the whole reply is a single label.
        """
        content = json.dumps(features.to_dict(), ensure_ascii=False)
        raw = self._chat(_STYLE_SYSTEM_PROMPT, content).strip().lower()
        # Normalise punctuation so "rock." / "The style is rock" both parse.
        tokens = [t.strip(".,;:!?()[]{}'\"") for t in raw.split()]
        for token in tokens:
            if token in _VALID_STYLES:
                return token
        for token in tokens:
            alias = _STYLE_ALIASES.get(token)
            if alias:
                return alias
        # Last resort: substring match against canonical styles.
        for style in _VALID_STYLES:
            if style in raw:
                return style
        logger.warning("LLM returned unrecognised style label: %s", raw)
        return "rock"  # safe default (most common guitar style)

    def propose_rewrite(self, request: RewriteRequest) -> RewriteResponse:
        """Propose note rewrite decisions via LLM."""
        user_content = json.dumps(
            {
                "features": request.features.to_dict(),
                "style_label": request.style_label,
                "policy": {
                    "midi_fidelity": request.policy.midi_fidelity,
                    "max_deletions": request.policy.max_deletions,
                    "max_transpositions": request.policy.max_transpositions,
                },
                "tuning": request.tuning_info,
                "notes": request.note_summaries[:200],  # cap to avoid token overflow
            },
            ensure_ascii=False,
        )
        raw_text = self._chat(_REWRITE_SYSTEM_PROMPT, user_content)
        return _parse_rewrite_response(raw_text)


def _parse_rewrite_response(raw_text: str) -> RewriteResponse:
    """Parse the LLM's JSON response into a RewriteResponse.

    Robust to common LLM quirks: markdown code fences, surrounding prose,
    and trailing text after the JSON object.
    """
    text = raw_text.strip()
    if not text:
        logger.warning("LLM returned empty rewrite response")
        return RewriteResponse(raw={"raw_text": raw_text})

    # Strip markdown fences: ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line, then any trailing fence line.
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract the first JSON object from the text.
        import re

        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                logger.warning("LLM returned non-JSON rewrite response: %s", raw_text[:200])
                return RewriteResponse(raw={"raw_text": raw_text})
        else:
            logger.warning("LLM returned non-JSON rewrite response: %s", raw_text[:200])
            return RewriteResponse(raw={"raw_text": raw_text})

    decisions: list[RewriteDecision] = []
    for item in data.get("decisions", []):
        try:
            decisions.append(
                RewriteDecision(
                    index=int(item["index"]),
                    operation=str(item["operation"]),
                    pitch=item.get("pitch"),
                    reason=str(item.get("reason", "")),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping malformed decision %r: %s", item, exc)

    return RewriteResponse(decisions=decisions, raw=data)


__all__ = ["OpenAICompatibleAdvisor"]
