from __future__ import annotations
from typing import Tuple
import re

# Character class finders
_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_DIGIT = re.compile(r"\d")
_SYMBOL = re.compile(r"[^A-Za-z0-9]")

# Very small denylist — can expand separately from a file if desired
COMMON_SMALL = {
    "password","passw0rd","123456","123456789","qwerty","letmein","welcome",
    "admin","iloveyou","monkey","dragon","111111","abc123","password1",
}

# Lightweight, practical email pattern:
# - keeps it permissive but sane (no DNS lookups)
# - allows IDNA/punycode domain labels like xn--...
_EMAIL_RE = re.compile(
    r"^(?P<local>[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64})@(?P<domain>(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z0-9-]{2,63})$"
)

def is_valid_email(email: str) -> Tuple[bool, str]:
    """
    Fast, pragmatic email validator.
    Returns (ok, msg). msg is empty when ok=True.
    Does NOT perform DNS lookups; suitable for form validation.
    """
    e = (email or "").strip()
    if not e:
        return False, "Email is required."
    if len(e) > 254:
        return False, "Email is too long."

    m = _EMAIL_RE.match(e)
    if not m:
        return False, "Enter a valid email address."

    local = m.group("local")
    domain = m.group("domain")

    # Disallow leading/trailing dot in local, and consecutive dots
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return False, "Enter a valid email address."

    # Per RFC, labels must not start/end with hyphen; also avoid all-numeric TLDs
    labels = domain.split(".")
    for label in labels:
        if label.startswith("-") or label.endswith("-") or not label:
            return False, "Enter a valid email address."

    tld = labels[-1]
    if tld.isdigit():
        return False, "Enter a valid email address."

    return True, ""

def check_password_strength(
    pwd: str,
    email: str = "",
    *,
    min_length: int = 12,
    require_upper: bool = True,
    require_lower: bool = True,
    require_digit: bool = True,
    require_symbol: bool = True,
    disallow_common: bool = True,
) -> Tuple[bool, str]:
    """
    Returns (ok, msg) describing the first unmet requirement.
    """
    pwd = (pwd or "").strip()
    if len(pwd) < min_length:
        return False, f"Password must be at least {min_length} characters."

    if require_upper and not _UPPER.search(pwd):
        return False, "Include at least one uppercase letter."
    if require_lower and not _LOWER.search(pwd):
        return False, "Include at least one lowercase letter."
    if require_digit and not _DIGIT.search(pwd):
        return False, "Include at least one number."
    if require_symbol and not _SYMBOL.search(pwd):
        return False, "Include at least one symbol."

    # avoid trivial relationship to email local part
    local = (email or "").split("@", 1)[0].lower()
    if local and local in pwd.lower():
        return False, "Password must not contain your email username."

    if disallow_common and pwd.lower() in COMMON_SMALL:
        return False, "Choose a more unique password."

    return True, ""

# Backwards/forwards-compatible name some modules import
def validate_strength(
    pwd: str,
    email: str = "",
    **kwargs,
) -> Tuple[bool, str]:
    """
    Thin alias so existing imports like
      `from app.auth.passwords import validate_strength`
    continue to work. Returns (ok, msg) exactly like check_password_strength.
    """
    return check_password_strength(pwd, email, **kwargs)
