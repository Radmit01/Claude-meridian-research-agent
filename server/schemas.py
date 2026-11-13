"""Request bodies. Optional[...] rather than `X | None`: pydantic evaluates
annotations at runtime, and the project must also run on Python 3.9."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    question: str = Field(..., min_length=8, max_length=2000)


class SyncRequest(BaseModel):
    force: bool = False
