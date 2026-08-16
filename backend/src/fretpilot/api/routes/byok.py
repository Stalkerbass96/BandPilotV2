"""BYOK routes — configure, test, and manage user LLM API keys."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fretpilot.ai.crypto import KeyVault, KeyVaultError
from fretpilot.ai.models import AIProviderError
from fretpilot.ai.providers.openai_compatible import OpenAICompatibleAdvisor
from fretpilot.api.deps import get_current_user, get_key_vault_dependency
from fretpilot.db.models import ByokConfig, User
from fretpilot.db.session import get_db

router = APIRouter()


class ByokRequest(BaseModel):
    provider: str = Field(default="openai_compatible")
    api_key: str = Field(min_length=1, max_length=512)
    base_url: str | None = Field(default=None)
    model: str | None = Field(default=None)


class ByokResponse(BaseModel):
    provider: str
    key_masked: str
    base_url: str | None = None
    model: str | None = None


class ByokTestResponse(BaseModel):
    ok: bool
    message: str


def _resolve_base_url(base_url: str | None) -> str:
    return base_url or "https://api.openai.com/v1"


def _save_config(
    db: Session, user: User, req: ByokRequest, vault: KeyVault
) -> ByokConfig:
    """Save or update the user's BYOK config."""
    encrypted = vault.encrypt(req.api_key)
    config = db.query(ByokConfig).filter(ByokConfig.user_id == user.id).first()
    if config is None:
        config = ByokConfig(
            user_id=user.id,
            provider=req.provider,
            encrypted_key=encrypted,
            base_url=req.base_url,
            model=req.model,
        )
        db.add(config)
    else:
        config.provider = req.provider
        config.encrypted_key = encrypted
        config.base_url = req.base_url
        config.model = req.model
    db.commit()
    db.refresh(config)
    return config


@router.get("", response_model=ByokResponse | None)
def get_byok(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ByokResponse | None:
    """Return the current BYOK config (masked key)."""
    config = db.query(ByokConfig).filter(ByokConfig.user_id == user.id).first()
    if config is None:
        return None
    return ByokResponse(
        provider=config.provider,
        key_masked=KeyVault.mask(_decrypt_safe(config, db, user)),
        base_url=config.base_url,
        model=config.model,
    )


def _decrypt_safe(config: ByokConfig, db: Session, user: User) -> str:
    """Decrypt the API key, returning a placeholder on failure."""
    vault = get_key_vault_dependency()
    try:
        return vault.decrypt(config.encrypted_key)
    except KeyVaultError:
        return "****"


@router.post("", response_model=ByokResponse)
def save_byok(
    req: ByokRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    vault: KeyVault = Depends(get_key_vault_dependency),
) -> ByokResponse:
    """Save or update the BYOK configuration."""
    config = _save_config(db, user, req, vault)
    return ByokResponse(
        provider=config.provider,
        key_masked=KeyVault.mask(req.api_key),
        base_url=config.base_url,
        model=config.model,
    )


@router.post("/test", response_model=ByokTestResponse)
def test_byok(req: ByokRequest) -> ByokTestResponse:
    """Test the LLM connection with the provided credentials."""
    advisor = OpenAICompatibleAdvisor(
        api_key=req.api_key,
        model=req.model or "gpt-4o-mini",
        base_url=_resolve_base_url(req.base_url),
    )
    try:
        from fretpilot.ai.advisor import extract_features
        from fretpilot.ai.models import TrackFeatures

        features = TrackFeatures(
            note_count=10, pitch_min=40, pitch_max=64, pitch_range_semitones=24,
            mean_velocity=80, mean_duration_beats=0.5, short_note_ratio=0.3,
            chord_onset_ratio=0.2, mean_polyphony=1.2, low_register_ratio=0.4,
            repeated_pitch_ratio=0.1,
        )
        advisor.infer_style(features)
        return ByokTestResponse(ok=True, message="LLM connection successful")
    except AIProviderError as exc:
        return ByokTestResponse(ok=False, message=str(exc))


@router.delete("", response_model=dict)
def delete_byok(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Delete the BYOK configuration."""
    config = db.query(ByokConfig).filter(ByokConfig.user_id == user.id).first()
    if config is not None:
        db.delete(config)
        db.commit()
    return {"ok": True}
