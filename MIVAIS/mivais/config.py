"""
MIVAIS library-level configuration.

Loaded from `mivais_config.yaml` next to agents_config.yaml.
Controls built-in infrastructure features for every VA system.

Example mivais_config.yaml:

    chat:
      enabled: true
      history_size: 50
    cursors:
      enabled: true
    audit:
      enabled: true
      recording_dir: recordings
    broadcast:
      exclude_keys: [dataset]
"""

from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class ChatConfig:
    enabled: bool = True
    history_size: int = 50


@dataclass
class CursorConfig:
    enabled: bool = True


@dataclass
class AuditConfig:
    enabled: bool = True
    recording_dir: str = "recordings"


@dataclass
class BroadcastConfig:
    exclude_keys: list[str] = field(default_factory=list)


@dataclass
class MivaisConfig:
    """Top-level library configuration."""
    chat: ChatConfig = field(default_factory=ChatConfig)
    cursors: CursorConfig = field(default_factory=CursorConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    broadcast: BroadcastConfig = field(default_factory=BroadcastConfig)

    @classmethod
    def load(cls, path: str | Path) -> "MivaisConfig":
        """Load from a YAML file.
        Missing keys use defaults."""
        import yaml

        path = Path(path)
        if not path.exists():
            return cls()
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        cfg = cls()
        if "chat" in raw:
            cfg.chat = ChatConfig(**{k: v for k, v in raw["chat"].items() if k in ChatConfig.__dataclass_fields__})
        if "cursors" in raw:
            cfg.cursors = CursorConfig(**{k: v for k, v in raw["cursors"].items() if k in CursorConfig.__dataclass_fields__})
        if "audit" in raw:
            cfg.audit = AuditConfig(**{k: v for k, v in raw["audit"].items() if k in AuditConfig.__dataclass_fields__})
        if "broadcast" in raw:
            cfg.broadcast = BroadcastConfig(**{k: v for k, v in raw["broadcast"].items() if k in BroadcastConfig.__dataclass_fields__})
        return cfg

    @classmethod
    def default(cls) -> "MivaisConfig":
        """Return default configuration (all features enabled)."""
        return cls()
