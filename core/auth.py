"""Mock authentication (D4). See SECURITY_NOTES.md for what production needs."""
import hashlib
import hmac
import secrets


def hash_password(password: str, salt: str | None = None) -> str:
    """Salted PBKDF2 hash, stored as "salt$hash"."""
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), stored)


# Which pages each role may open (page keys are defined in app.py)
ROLE_PAGES = {
    "owner": ["tour", "overview", "location", "forecast", "security"],
    "manager": ["tour", "actions", "location", "forecast", "security"],
}
