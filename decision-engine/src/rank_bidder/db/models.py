"""Pydantic v2 models for sites + keywords (Story 1.2).

DB ↔ model 변환 규칙:
- boolean: DB INTEGER 0/1 ↔ Python bool (field_validator mode='before')
- datetime: SQLite ``datetime('now')`` → UTC-aware datetime
- aliases (Story 1.10): DB TEXT(JSON) ↔ Python ``list[str]`` (field_validator mode='before')
"""

from __future__ import annotations

import json
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
        # Python 3.11+ ``datetime.fromisoformat`` 가 'T'/' ' 분리자 + 'Z' suffix
        # 모두 네이티브 지원. SQLite ``datetime('now')`` = "YYYY-MM-DD HH:MM:SS" naive UTC.
        parsed = datetime.fromisoformat(value.strip())
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


class SiteRead(Site):
    """Public read DTO. 현재는 ``Site``와 동일하지만 future serializer 분리 hook."""


# ---------------------------------------------------------------------------
# Keyword
# ---------------------------------------------------------------------------


def _decode_aliases_from_db(value: Any) -> Any:
    """DB TEXT(JSON) → list[str] (Story 1.10 KeywordBase.aliases pre-validator)."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"aliases must be valid JSON: {exc}") from exc
        if not isinstance(decoded, list):
            raise ValueError("aliases JSON must decode to a list")
        return decoded
    return value


def _normalize_aliases(value: list[Any]) -> list[str]:
    """Post-decode validator — 각 alias str+strip+NFC+non-empty+≤200, 중복 거부.

    Story 1.10 review patch (2026-05-28): NFC 정규화를 DB 박제 시점에 적용한다.
    parser ``_normalize`` 도 NFC 적용하므로 무관해 보이지만, DB 일관성(dashboard
    검색 / 운영자 grep / future SELECT WHERE term=?) 차원에서 모든 alias bytes를
    NFC로 통일한다. macOS 클립보드/IME가 NFD로 보내는 한글 입력도 박제 시점에 NFC.
    """
    import unicodedata

    cleaned: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"aliases[{idx}] must be str (got {type(item).__name__})")
        stripped = unicodedata.normalize("NFC", item.strip())
        if not stripped:
            raise ValueError(f"aliases[{idx}] must not be empty/whitespace")
        if len(stripped) > 200:
            raise ValueError(f"aliases[{idx}] too long ({len(stripped)} > 200)")
        cleaned.append(stripped)
    if len(cleaned) != len(set(cleaned)):
        # Story 1.10 review patch: PII 회피 위해 raw alias 노출하지 않고 index만.
        dups = [i for i, a in enumerate(cleaned) if cleaned.count(a) > 1]
        raise ValueError(f"duplicate aliases not allowed at indices {sorted(set(dups))}")
    return cleaned


class KeywordBase(BaseModel):
    model_config = _BASE_CONFIG

    term: str = Field(min_length=1, max_length=200)
    target_rank: int = Field(ge=1, le=10)
    bid_cap: int = Field(ge=100, le=100000)
    enabled: bool = True
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, v: Any) -> bool:
        return _to_bool(v)

    @field_validator("aliases", mode="before")
    @classmethod
    def _coerce_aliases(cls, v: Any) -> Any:
        return _decode_aliases_from_db(v)

    @field_validator("aliases", mode="after")
    @classmethod
    def _validate_aliases(cls, v: list[Any]) -> list[str]:
        return _normalize_aliases(v)


class KeywordCreate(KeywordBase):
    id: str = Field(min_length=1, max_length=64)
    site_id: str = Field(min_length=1, max_length=64)
    adgroup_id: str | None = Field(default=None, max_length=64)


class KeywordUpdate(BaseModel):
    model_config = _BASE_CONFIG

    term: str | None = Field(default=None, min_length=1, max_length=200)
    target_rank: int | None = Field(default=None, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100000)
    enabled: bool | None = None
    aliases: list[str] | None = Field(default=None, max_length=20)

    @field_validator("enabled", mode="before")
    @classmethod
    def _coerce_enabled(cls, v: Any) -> bool | None:
        return None if v is None else _to_bool(v)

    @field_validator("aliases", mode="after")
    @classmethod
    def _validate_aliases(cls, v: list[Any] | None) -> list[str] | None:
        if v is None:
            return None
        return _normalize_aliases(v)


class Keyword(KeywordBase):
    id: str
    site_id: str
    adgroup_id: str | None = None
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


class KeywordRead(Keyword):
    """Public read DTO. 현재는 ``Keyword``와 동일하지만 future serializer 분리 hook."""


# ---------------------------------------------------------------------------
# CycleEntry — D15 (b) state machine row (Story 1.6)
# ---------------------------------------------------------------------------

_CYCLE_STATES = {"PLANNED", "MEASURED", "DECIDED", "PUT_SENT", "COMMITTED", "FAILED"}


class CycleEntryCreate(BaseModel):
    model_config = _BASE_CONFIG

    cycle_id: str = Field(min_length=1, max_length=64)
    keyword_id: str = Field(min_length=1, max_length=64)
    state: str = Field(default="PLANNED")

    @field_validator("state")
    @classmethod
    def _validate_state(cls, v: str) -> str:
        if v not in _CYCLE_STATES:
            raise ValueError(f"state must be in {sorted(_CYCLE_STATES)}, got {v!r}")
        return v


class CycleEntry(CycleEntryCreate):
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> datetime:
        return _to_utc_datetime(v)

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Measurement — sampler 결과 영속 (Story 1.6)
# ---------------------------------------------------------------------------


class MeasurementCreate(BaseModel):
    model_config = _BASE_CONFIG

    keyword_id: str = Field(min_length=1, max_length=64)
    rank_samples: list[int | None] = Field(min_length=1)
    rank_final: int | None = Field(default=None, ge=1, le=100)
    current_bid: int = Field(ge=0)


class Measurement(BaseModel):
    model_config = _BASE_CONFIG

    id: int
    keyword_id: str
    measured_at: datetime
    rank_samples: list[int | None]
    rank_final: int | None
    current_bid: int

    @field_validator("measured_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> datetime:
        return _to_utc_datetime(v)

    @field_validator("rank_samples", mode="before")
    @classmethod
    def _coerce_samples(cls, v: Any) -> list[int | None]:
        # DB는 TEXT(JSON) — 호출자가 json.loads 후 전달하거나, 여기서 처리.
        if isinstance(v, str):
            import json as _json

            return _json.loads(v)
        return v

    @field_serializer("measured_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Decision — 결정 엔진 출력 log (Story 1.6)
# ---------------------------------------------------------------------------

_DECISION_VALUES = {"BID_UP", "BID_DOWN", "HOLD", "CAP_REACHED", "SKIP_STALE"}


class DecisionCreate(BaseModel):
    model_config = _BASE_CONFIG

    keyword_id: str = Field(min_length=1, max_length=64)
    cycle_id: str = Field(min_length=1, max_length=64)
    decision: str
    old_bid: int = Field(ge=0)
    new_bid: int = Field(ge=0)
    rank_observed: int | None = Field(default=None, ge=1, le=100)
    reason: str | None = None
    api_response_status: int | None = None
    api_error: str | None = None
    # Story 3.1 D17: 결정 시점 effective bid_cap. None 허용 — pre-3.1 row backward compat.
    bid_cap: int | None = Field(default=None, ge=100, le=100000)

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, v: str) -> str:
        if v not in _DECISION_VALUES:
            raise ValueError(f"decision must be in {sorted(_DECISION_VALUES)}, got {v!r}")
        return v


class Decision(DecisionCreate):
    id: int
    decided_at: datetime

    @field_validator("decided_at", mode="before")
    @classmethod
    def _coerce_dt(cls, v: Any) -> datetime:
        return _to_utc_datetime(v)

    @field_serializer("decided_at")
    def _serialize_dt(self, v: datetime) -> str:
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Policy — Multi-time policy row (Story 3.1, FR-7)
# ---------------------------------------------------------------------------

_POLICY_SCOPE_TYPES = {"site", "keyword"}
MINUTES_PER_WEEK = 7 * 24 * 60  # 10080


class PolicyBase(BaseModel):
    model_config = _BASE_CONFIG

    scope_type: str
    scope_id: str = Field(min_length=1, max_length=64)
    start_minute_of_week: int = Field(ge=0, le=MINUTES_PER_WEEK - 1)
    duration_minutes: int = Field(ge=1, le=MINUTES_PER_WEEK)
    target_rank: int = Field(ge=1, le=10)
    bid_cap: int = Field(ge=100, le=100000)

    @field_validator("scope_type")
    @classmethod
    def _validate_scope_type(cls, v: str) -> str:
        if v not in _POLICY_SCOPE_TYPES:
            raise ValueError(f"scope_type must be in {sorted(_POLICY_SCOPE_TYPES)}, got {v!r}")
        return v


class PolicyCreate(PolicyBase):
    """신규 정책 insert payload — id는 AUTOINCREMENT."""


class PolicyUpdate(BaseModel):
    model_config = _BASE_CONFIG

    start_minute_of_week: int | None = Field(default=None, ge=0, le=MINUTES_PER_WEEK - 1)
    duration_minutes: int | None = Field(default=None, ge=1, le=MINUTES_PER_WEEK)
    target_rank: int | None = Field(default=None, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100000)


class Policy(PolicyBase):
    id: int
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
