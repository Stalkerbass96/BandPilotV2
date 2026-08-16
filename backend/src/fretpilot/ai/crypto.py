"""BYOK API key encryption using Fernet symmetric encryption.

The master key is read from the environment variable at startup. API keys
are encrypted before database storage and decrypted only when making LLM
calls. API responses always return masked keys.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class KeyVaultError(Exception):
    """Raised when key encryption/decryption fails."""


class KeyVault:
    """BYOK API key symmetric encryption vault."""

    def __init__(self, master_key: str | bytes) -> None:
        if isinstance(master_key, str):
            master_key = master_key.encode()
        try:
            self._fernet = Fernet(master_key)
        except (ValueError, TypeError) as exc:
            raise KeyVaultError(f"Invalid master key: {exc}") from exc

    def encrypt(self, api_key: str) -> str:
        """Encrypt an API key; return the ciphertext as a string."""
        return self._fernet.encrypt(api_key.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        """Decrypt an encrypted API key; raise on tampering."""
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except InvalidToken as exc:
            raise KeyVaultError("Failed to decrypt API key (invalid token)") from exc

    @staticmethod
    def mask(api_key: str) -> str:
        """Return a masked representation: sk-****1234."""
        if len(api_key) <= 8:
            return "****"
        return f"{api_key[:3]}****{api_key[-4:]}"

    @staticmethod
    def generate_master_key() -> str:
        """Generate a new Fernet master key (for dev setup)."""
        return Fernet.generate_key().decode()


def get_key_vault(master_key: str | None = None) -> KeyVault:
    """Build a KeyVault from the given key or the settings."""
    if master_key is None:
        from fretpilot.config import get_settings

        master_key = get_settings().master_key
    if not master_key:
        master_key = KeyVault.generate_master_key()
    return KeyVault(master_key)


__all__ = ["KeyVault", "KeyVaultError", "get_key_vault"]
