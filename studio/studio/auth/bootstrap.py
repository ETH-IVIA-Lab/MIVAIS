"""On first boot, mint an AdminUser from STUDIO_ADMIN_USERNAME / _PASSWORD.

Idempotent — does nothing once at least one AdminUser exists. The env user is
the *bootstrap* admin; once Studio has any AdminUser, the env credentials are
no longer consulted. This is what lets multi-admin operate while the .env
remains the recovery path for the first instance.
"""
from __future__ import annotations

import logging

from studio.auth.password import hash_password
from studio.models import AdminUser
from studio.settings import get_settings

log = logging.getLogger("studio.auth")


async def ensure_bootstrap_admin() -> None:
    if await AdminUser.find().limit(1).count() > 0:
        return
    s = get_settings()
    if not s.admin_username or not s.admin_password:
        log.warning("no AdminUser in database and no STUDIO_ADMIN_* env vars set — admin login will fail")
        return
    user = AdminUser(
        username=s.admin_username,
        pw_hash=hash_password(s.admin_password),
    )
    await user.insert()
    log.info("bootstrapped admin user '%s' from environment", s.admin_username)
