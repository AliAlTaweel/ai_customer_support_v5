"""Reversible encryption for Shopify access tokens (stored, not hashed, since the
plaintext token must be recovered to call Shopify's Admin API)."""

from cryptography.fernet import Fernet
from config import get_settings


def _cipher() -> Fernet:
    key = get_settings().SHOPIFY_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ValueError(
            "SHOPIFY_TOKEN_ENCRYPTION_KEY is not configured; cannot encrypt/decrypt "
            "Shopify access tokens."
        )
    return Fernet(key.encode())


def encrypt_shopify_token(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_shopify_token(ciphertext: str) -> str:
    return _cipher().decrypt(ciphertext.encode()).decode()
