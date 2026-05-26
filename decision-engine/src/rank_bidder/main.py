"""Decision Engine entrypoint.

Story 1.1 stub — Story 1.9에서 강화됨 (FastAPI app + lifespan + cron 통합 + /health).
"""

from fastapi import FastAPI

app = FastAPI(title="Rank Bidder Decision Engine", version="0.1.0")


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
