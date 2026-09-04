"""Runtime configuration loaded from environment variables.

A single Settings instance is read once at startup; subsequent reads return
the cached value. Variables are flat and prefixed with STUDIO_.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_INSECURE_JWT_SECRETS = {"", "dev-only-change-me", "smoke-secret-do-not-use-in-prod"}
_INSECURE_PASSWORDS = {"", "change-me", "smoke"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STUDIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # MongoDB
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "mivais_studio"

    admin_username: str = "admin"
    admin_password: str = "change-me"
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 60 * 12

    # File system
    data_dir: Path = Path("./data")
    studies_dir: Path = Path("./studies")
    studies_seed_dir: Path | None = None

    # VA process management
    va_port_range_start: int = 7100
    va_port_range_end: int = 7199
    va_spawn_timeout_seconds: int = 30
    va_shutdown_grace_seconds: int = 5

    
    external_va_base_url: str = ""

    
    external_va_health_base_url: str = ""

    @property
    def external_va_health_base(self) -> str:
        return self.external_va_health_base_url or self.external_va_base_url

    
    voyager_base_url: str = ""
    voyager_health_base_url: str = ""

    @property
    def voyager_health_base(self) -> str:
        return self.voyager_health_base_url or self.voyager_base_url

    
    proactive_base_url: str = ""
    proactive_health_base_url: str = ""

    @property
    def proactive_health_base(self) -> str:
        return self.proactive_health_base_url or self.proactive_base_url

    
    public_base_url: str = ""

    # Audio capture + transcription
    audio_max_chunk_bytes: int = 5 * 1024 * 1024   # 5 MB hard cap per chunk
    whisper_device: str = "cpu"                    # "cpu" | "cuda"
    whisper_compute_type: str = "int8"             # int8 is ~3x realtime on CPU
    whisper_default_model: str = "small"           # tiny | base | small | medium | large-v3
    whisper_default_language: str = "auto"
    whisper_worker_enabled: bool = True            # set False to disable transcription

    # Screen + mic session recording (video)
    video_max_chunk_bytes: int = 16 * 1024 * 1024  # 16 MB hard cap per video chunk

    
    default_lang: str = "en"

    
    environment: str = "development"

    
    cookie_secure: bool | None = None

    # Admin login throttle (per-IP sliding window).
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def cookie_secure_effective(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    @model_validator(mode="after")
    def _reject_insecure_secrets_in_production(self) -> "Settings":
        """Fail fast at boot if production is configured with placeholder secrets.

        This is the guard the audit flagged as missing: a publicly-known JWT
        secret / admin password must never reach a real deployment. In
        development these placeholders stay allowed so local runs just work.
        """
        if not self.is_production:
            return self
        problems = []
        if self.jwt_secret in _INSECURE_JWT_SECRETS or len(self.jwt_secret) < 32:
            problems.append(
                "STUDIO_JWT_SECRET must be a strong, non-default value (>=32 chars); "
                "generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        if self.admin_password in _INSECURE_PASSWORDS or len(self.admin_password) < 8:
            problems.append(
                "STUDIO_ADMIN_PASSWORD must be set to a non-default value (>=8 chars)"
            )
        if problems:
            raise ValueError(
                "Refusing to start in production with insecure configuration:\n  - "
                + "\n  - ".join(problems)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
