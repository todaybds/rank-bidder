"""Decision Engine entrypoint — Story 1.2 lifespan + migrations.

Story 1.9에서 systemd unit, /health DB heartbeat, cron 통합으로 강화 예정.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from rank_bidder.db.migrate import DEFAULT_MIGRATIONS_DIR, up

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup에서 SQLite 마이그레이션 적용.

    - ``RANKBIDDER_DB_PATH`` 미설정 + ``RANKBIDDER_ENV != prod`` → warning + skip
      (TestClient/unit test 호환).
    - ``RANKBIDDER_DB_PATH`` 미설정 + ``RANKBIDDER_ENV == prod`` → 즉시 fail
      (prod에서 env 누락이 silent boot로 가는 사고 차단).
    - 그 외 모든 예외 (PRAGMA verification 실패, sqlite3 OperationalError 등)는
      그대로 propagate — startup 실패로 처리.
    """
    db_path_set = bool(os.environ.get("RANKBIDDER_DB_PATH"))
    is_prod = os.environ.get("RANKBIDDER_ENV", "").lower() == "prod"

    if not db_path_set:
        if is_prod:
            raise RuntimeError("RANKBIDDER_DB_PATH required when RANKBIDDER_ENV=prod")
        log.warning(
            "startup.migrations_skipped",
            reason="RANKBIDDER_DB_PATH not set (non-prod env)",
        )
        yield
        return

    applied = up(DEFAULT_MIGRATIONS_DIR)
    log.info("startup.migrations_applied", count=applied)
    yield
    # shutdown hook 자리 (Story 1.9에서 graceful drain).


app = FastAPI(
    title="Rank Bidder Decision Engine",
    version="0.1.0",
    lifespan=lifespan,
)

# Story 4.1 — Bearer middleware (env-gated, /health bypass)
from rank_bidder.auth.bearer import install as install_bearer  # noqa: E402

install_bearer(app)

# Story 2.1 — keyword bulk import router
from rank_bidder.api.imports import router as imports_router  # noqa: E402

# Story 2.2 — keyword toggle router
from rank_bidder.api.keywords import router as keywords_router  # noqa: E402

# Story 2.3 — site toggle router
from rank_bidder.api.sites import router as sites_router  # noqa: E402

# Story 3.3 — policies CRUD router
from rank_bidder.api.policies import router as policies_router  # noqa: E402

app.include_router(imports_router)
app.include_router(keywords_router)
app.include_router(sites_router)
app.include_router(policies_router)


@app.get("/health")
def health() -> dict[str, object]:
    """Health probe — Story 1.9에서 DB heartbeat row insert로 강화 (D26 채널 5).

    /health 호출 시 heartbeats 테이블에 1행 insert + 200 응답.
    DB connection 실패 시 200 + heartbeat_id=None (probe 자체는 살아있음 표시).
    """
    try:
        from rank_bidder.jobs.keep_alive import insert_heartbeat

        row_id = insert_heartbeat(source="health")
        return {"ok": True, "heartbeat_id": row_id}
    except Exception as exc:  # noqa: BLE001 — probe는 결코 5xx 안 됨
        log.warning("health.heartbeat_failed", error=str(exc))
        return {"ok": True, "heartbeat_id": None, "warning": str(exc)}


def main() -> None:
    """uvicorn 진입점 (`uv run rank-bidder`).

    Story 1.9에서 systemd unit로 자동 실행. 로컬 dev는 `fastapi dev` 권장.
    """
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
