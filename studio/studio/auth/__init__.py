"""Admin authentication: argon2id passwords + JWT cookie."""
from studio.auth.bootstrap import ensure_bootstrap_admin
from studio.auth.deps import optional_admin, require_admin
from studio.auth.jwt import create_token, decode_token
from studio.auth.password import hash_password, verify_password

__all__ = [
    "create_token",
    "decode_token",
    "ensure_bootstrap_admin",
    "hash_password",
    "optional_admin",
    "require_admin",
    "verify_password",
]
