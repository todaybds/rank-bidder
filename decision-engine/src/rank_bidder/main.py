"""Decision Engine entrypoint — Story 1.2 lifespan + migrations.

Story 1.9에서 systemd unit, /health DB heartbeat, cron 통합으로 강화 예정.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from rank_bidder.db.migrate import DEFAULT_MIGRATIONS_DIR, up

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup에서 SQLite 마이그레이션 적용.

    ``RANKBIDDER_DB_PATH``가 없으면 (예: TestClient unit 테스트 환경) 경고 후 skip.
    Production 배포는 systemd EnvironmentFile로 항상 설정.
    """
    try:
        applied = up(DEFAULT_MIGRATIONS_DIR)
        log.info("startup.migrations_applied", count=applied)
    except RuntimeError as exc:
        log.warning("startup.migrations_skipped", reason=str(exc))
    yield
    # shutdown hook 자리 (Story 1.9에서 graceful drain).


app = FastAPI(
    title="Rank Bidder Decision Engine",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, bool]:
    """Health probe. Story 1.9에서 DB heartbeat insert로 강화."""
    return {"ok": True}


def main() -> None:
    """uvicorn 진입점 (`uv run rank-bidder`).

    Story 1.9에서 systemd unit로 자동 실행. 로컬 dev는 `fastapi dev` 권장.
    """
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
