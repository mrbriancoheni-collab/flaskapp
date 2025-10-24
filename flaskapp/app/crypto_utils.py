# app/crypto_utils.py
"""
Encryption utilities for storing sensitive credentials at rest.
Uses Fernet (symmetric encryption) with a key from environment.
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet
from flask import current_app


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


def get_fernet_key() -> bytes:
    """
    Get the Fernet encryption key from app config.
    Raises EncryptionError if not configured.
    """
    key = current_app.config.get("APP_FERNET_KEY")
    if not key:
        raise EncryptionError(
            "APP_FERNET_KEY not configured. "
            "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    # Handle both string and bytes
    if isinstance(key, str):
        key = key.encode('utf-8')

    return key


def encrypt_string(plaintext: str) -> str:
    """
    Encrypt a string and return base64-encoded ciphertext.

    Args:
        plaintext: The string to encrypt

    Returns:
        Base64-encoded encrypted string

    Raises:
        EncryptionError: If encryption fails
    """
    if not plaintext:
        return ""

    try:
        fernet = Fernet(get_fernet_key())
        encrypted_bytes = fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')
    except Exception as e:
        raise EncryptionError(f"Encryption failed: {e}")


def decrypt_string(ciphertext: str) -> str:
    """
    Decrypt a base64-encoded ciphertext string.

    Args:
        ciphertext: Base64-encoded encrypted string

    Returns:
        Decrypted plaintext string

    Raises:
        EncryptionError: If decryption fails
    """
    if not ciphertext:
        return ""

    try:
        fernet = Fernet(get_fernet_key())
        decrypted_bytes = fernet.decrypt(ciphertext.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        raise EncryptionError(f"Decryption failed: {e}")


def is_encrypted(value: str) -> bool:
    """
    Check if a string looks like it's already encrypted (Fernet format).
    Fernet tokens start with 'gAAAAA' after base64 encoding.

    This is a heuristic - not foolproof but good enough for migration detection.
    """
    if not value:
        return False

    # Fernet tokens are base64 and typically start with 'gAAAAA'
    # (version byte 0x80 in Fernet v1)
    return value.startswith('gAAAAA')


def generate_key() -> str:
    """
    Generate a new Fernet key for APP_FERNET_KEY environment variable.

    Returns:
        Base64-encoded Fernet key as string
    """
    return Fernet.generate_key().decode('utf-8')


# Convenience functions for common use cases

def encrypt_json_credentials(creds_dict: dict) -> str:
    """
    Encrypt a JSON credentials dictionary (for Google OAuth, etc.).

    Args:
        creds_dict: Dictionary containing credentials

    Returns:
        Encrypted JSON string
    """
    import json
    json_str = json.dumps(creds_dict)
    return encrypt_string(json_str)


def decrypt_json_credentials(encrypted_json: str) -> dict:
    """
    Decrypt JSON credentials back to dictionary.

    Args:
        encrypted_json: Encrypted JSON string

    Returns:
        Decrypted credentials dictionary
    """
    import json
    decrypted_str = decrypt_string(encrypted_json)
    if not decrypted_str:
        return {}
    return json.loads(decrypted_str)
