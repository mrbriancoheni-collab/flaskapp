# app/services/crypto.py
import os
from cryptography.fernet import Fernet

# Load key from environment
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
    return fernet.encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    """Decrypt a Fernet token back to a string."""
    return fernet.decrypt(s.encode()).decode()

