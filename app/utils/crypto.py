"""
Symmetric encryption for secrets stored at rest (API tokens, custom LLM
API keys, database connection credentials).

Reads the key from the ENCRYPTION_KEY environment variable (a
urlsafe-base64 Fernet key - generate one with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

decrypt() falls back to returning the input unchanged if it isn't valid
Fernet ciphertext, so rows written before encryption was added keep
working until they're next saved (at which point encrypt() protects
them going forward) instead of throwing on every read.
"""
import os
from cryptography.fernet import Fernet, InvalidToken

_key = os.getenv('ENCRYPTION_KEY')
_fernet = Fernet(_key.encode()) if _key else None

if not _fernet:
    print("⚠️  ENCRYPTION_KEY is not set - secrets (API tokens, custom LLM "
          "keys, database credentials) will be stored in plain text. Set "
          "ENCRYPTION_KEY to a Fernet key to encrypt them at rest.")


def encrypt(value):
    """Encrypt a string for storage. Returns the input unchanged if no
    ENCRYPTION_KEY is configured, or if the value is empty."""
    if not value:
        return value
    if not _fernet:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value):
    """Decrypt a value previously written by encrypt(). Returns the input
    unchanged if it isn't valid ciphertext (legacy plaintext row, or no
    ENCRYPTION_KEY configured) rather than raising."""
    if not value:
        return value
    if not _fernet:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return value
