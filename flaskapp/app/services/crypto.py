# app/services/crypto.py
# Legacy compatibility wrapper - now uses crypto_utils for all encryption
# This ensures all encryption uses the same system with better error handling

import os
from cryptography.fernet import Fernet

# Check for key at module load (backward compatibility with strict behavior)
_key = os.getenv("APP_FERNET_KEY")

if not _key:
    raise RuntimeError(
        "APP_FERNET_KEY is not set! "
        "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' "
        "and add it to your environment."
    )

try:
    fernet = Fernet(_key.encode())
except Exception as e:
    raise RuntimeError("APP_FERNET_KEY is invalid. Must be a valid base64 Fernet key.") from e


def encrypt(s: str) -> str:
    """Encrypt a string into a Fernet token."""
    # Use the unified encryption system
    from app.crypto_utils import encrypt_string
    return encrypt_string(s)


def decrypt(s: str) -> str:
    """Decrypt a Fernet token back to a string."""
    # Use the unified encryption system
    from app.crypto_utils import decrypt_string
    return decrypt_string(s)

