"""
Shared response models for the admin + participant JSON API.

"""
from __future__ import annotations

from pydantic import BaseModel


class OkResponse(BaseModel):
    """Bare acknowledgement body for mutations with nothing else to return."""

    ok: bool = True
