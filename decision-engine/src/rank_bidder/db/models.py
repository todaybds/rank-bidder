"""Pydantic v2 models for sites + keywords (Story 1.2).

DB ↔ model 변환 규칙:
- boolean: DB INTEGER 0/1 ↔ Python bool (field_validator mode='before')
- datetime: SQLite ``datetime('now')`` → UTC-aware datetime
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

_BASE_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "t", "yes", "y"}:
            return True
        if lowered in {"0", "false", "f", "no", "n"}:
            return False
    raise ValueError(f"bool 변환 실패: {value!r}")


def _to_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        # SQLite datetime('now') = "YYYY-MM-DD HH:MM:SS" (naive UTC)
        normalized = value.replace("T", " ").rstrip("Z").strip()
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise ValueError(f"datetime 변환 실패: {value!r}")


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------


class SiteBase(BaseModel):
    model_config = _BASE_CONFIG

    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, v: Any) -> bool:
        return _to_bool(v)


class SiteCreate(SiteBase):
    id: str = Field(min_length=1, max_length=64)


class SiteUpdate(BaseModel):
    model_config = _BASE_CONFIG

    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, v: Any) -> bool | None:
        return None if v is None else _to_bool(v)


class Site(SiteBase):
    id: str
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> datetime:
        return _to_utc_datetime(v)

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


SiteRead = Site


# ---------------------------------------------------------------------------
# Keyword
# ---------------------------------------------------------------------------


class KeywordBase(BaseModel):
    model_config = _BASE_CONFIG

    term: str = Field(min_length=1, max_length=200)
    target_rank: int = Field(ge=1, le=10)
    bid_cap: int = Field(ge=100, le=100000)
    enabled: bool = True

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, v: Any) -> bool:
        return _to_bool(v)


class KeywordCreate(KeywordBase):
    id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)


class KeywordUpdate(BaseModel):
    model_config = _BASE_CONFIG

    term: str | None = Field(default=None, min_length=1, max_length=200)
    target_rank: int | None = Field(default=None, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100000)
    enabled: bool | None = None

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, v: Any) -> bool | None:
        return None if v is None else _to_bool(v)


class Keyword(KeywordBase):
    id: str
    site_id: str
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> datetime:
        return _to_utc_datetime(v)

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


KeywordRead = Keyword
