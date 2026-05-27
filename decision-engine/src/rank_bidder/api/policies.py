"""GET/POST/PUT/DELETE /api/v1/policies — Story 3.3 (FR-16, D5 version counter).

scope_type ∈ {site, keyword}, scope_id 는 sites.id / keywords.id 와 의미적 FK.
중복 시간 구간은 허용 (D15 r) — UI 측 warning. server는 검증 없이 저장.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from rank_bidder.db.connection import get_connection, write_transaction
from rank_bidder.db.models import MINUTES_PER_WEEK, Policy, PolicyCreate, PolicyUpdate
from rank_bidder.db.repositories import keywords as keywords_repo
from rank_bidder.db.repositories import policies as policies_repo
from rank_bidder.db.repositories import sites as sites_repo
from rank_bidder.db.version import VersionConflictError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/policies", tags=["policies"])

_SCOPE_TYPES = {"site", "keyword"}


class PolicyCreateRequest(BaseModel):
    scope_type: str
    scope_id: str = Field(min_length=1, max_length=64)
    start_minute_of_week: int = Field(ge=0, le=MINUTES_PER_WEEK - 1)
    duration_minutes: int = Field(ge=1, le=MINUTES_PER_WEEK)
    target_rank: int = Field(ge=1, le=10)
    bid_cap: int = Field(ge=100, le=100000)

    @field_validator("scope_type")
    @classmethod
    def _validate_scope_type(cls, v: str) -> str:
        if v not in _SCOPE_TYPES:
            raise ValueError(f"scope_type must be in {sorted(_SCOPE_TYPES)}, got {v!r}")
        return v


class PolicyUpdateRequest(BaseModel):
    if_match_version: int = Field(ge=0)
    start_minute_of_week: int | None = Field(default=None, ge=0, le=MINUTES_PER_WEEK - 1)
    duration_minutes: int | None = Field(default=None, ge=1, le=MINUTES_PER_WEEK)
    target_rank: int | None = Field(default=None, ge=1, le=10)
    bid_cap: int | None = Field(default=None, ge=100, le=100000)


def _to_dto(p: Policy) -> dict:
    return {
        "id": p.id,
        "scope_type": p.scope_type,
        "scope_id": p.scope_id,
        "start_minute_of_week": p.start_minute_of_week,
        "duration_minutes": p.duration_minutes,
        "target_rank": p.target_rank,
        "bid_cap": p.bid_cap,
        "version": p.version,
        "created_at": p.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": p.updated_at.isoformat().replace("+00:00", "Z"),
    }


def _verify_scope_exists(conn, scope_type: str, scope_id: str) -> None:
    if scope_type == "site":
        if sites_repo.get(conn, scope_id) is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {"code": "SCOPE_NOT_FOUND", "scope_type": "site", "scope_id": scope_id}
                },
            )
    else:
        if keywords_repo.get(conn, scope_id) is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "SCOPE_NOT_FOUND",
                        "scope_type": "keyword",
                        "scope_id": scope_id,
                    }
                },
            )


@router.get("")
def list_policies(scope_type: str, scope_id: str) -> dict:
    """scope (type+id)의 모든 정책. wraparound 매치 여부 무관 — UI 가 표시."""
    if scope_type not in _SCOPE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_SCOPE_TYPE", "value": scope_type}},
        )
    with get_connection() as conn:
        rows = policies_repo.list_by_scope(conn, scope_type, scope_id)
    return {"items": [_to_dto(p) for p in rows], "count": len(rows)}


@router.post("")
def create_policy(req: PolicyCreateRequest) -> dict:
    with write_transaction() as conn:
        _verify_scope_exists(conn, req.scope_type, req.scope_id)
        p = policies_repo.create(
            conn,
            PolicyCreate(
                scope_type=req.scope_type,
                scope_id=req.scope_id,
                start_minute_of_week=req.start_minute_of_week,
                duration_minutes=req.duration_minutes,
                target_rank=req.target_rank,
                bid_cap=req.bid_cap,
            ),
        )
    log.info(
        "policies.created",
        policy_id=p.id,
        scope_type=p.scope_type,
        scope_id=p.scope_id,
        target_rank=p.target_rank,
        bid_cap=p.bid_cap,
    )
    return _to_dto(p)


@router.put("/{policy_id}")
def update_policy(policy_id: int, req: PolicyUpdateRequest) -> dict:
    try:
        with write_transaction() as conn:
            existing = policies_repo.get(conn, policy_id)
            if existing is None:
                raise HTTPException(
                    status_code=404,
                    detail={"error": {"code": "POLICY_NOT_FOUND", "policy_id": policy_id}},
                )
            updated = policies_repo.update(
                conn,
                policy_id,
                PolicyUpdate(
                    start_minute_of_week=req.start_minute_of_week,
                    duration_minutes=req.duration_minutes,
                    target_rank=req.target_rank,
                    bid_cap=req.bid_cap,
                ),
                expected_version=req.if_match_version,
            )
    except VersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "VERSION_MISMATCH",
                    "expected_version": req.if_match_version,
                    "current_version": exc.current_version,
                }
            },
        ) from exc

    log.info(
        "policies.updated",
        policy_id=updated.id,
        new_version=updated.version,
    )
    return _to_dto(updated)


@router.delete("/{policy_id}")
def delete_policy(policy_id: int, if_match_version: int) -> dict:
    try:
        with write_transaction() as conn:
            policies_repo.delete(conn, policy_id, expected_version=if_match_version)
    except VersionConflictError as exc:
        if exc.current_version is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "POLICY_NOT_FOUND", "policy_id": policy_id}},
            ) from exc
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "VERSION_MISMATCH",
                    "expected_version": if_match_version,
                    "current_version": exc.current_version,
                }
            },
        ) from exc

    log.info("policies.deleted", policy_id=policy_id)
    return {"result": "deleted", "policy_id": policy_id}
