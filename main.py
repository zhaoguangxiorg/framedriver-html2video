# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""FastAPI application entry point.

Exposes:
  - `GET /` and `/static/...` (mounted `presentation/web/static/` frontend)
  - `GET /api/sessions`, `POST /api/sessions`, ...
  - `POST /api/content/{project_id}`, `GET /api/content/{project_id}/stream`
  - `POST /api/ppt/{project_id}`, `GET /api/ppt/{project_id}/stream`
  - `GET /api/slides/...`
  - `POST /api/video/{project_id}`, `GET /api/video/{project_id}/progress`,
    `GET /api/video/{project_id}/download`

Run with:
    d:/.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from presentation.api import sessions_api
from presentation.api import content_api
from presentation.api import ppt_api
from presentation.api import slides_api
from presentation.api import video_api
from presentation.api import package_api
from presentation.api import models_api
from presentation.api import share_api
from domain.dal.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def create_app() -> FastAPI:
    init_db()
    logger.info("database tables ensured")

    app = FastAPI(title="PPT Video Generation API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions_api.router)
    app.include_router(sessions_api.messages_router)
    app.include_router(content_api.router)
    app.include_router(ppt_api.router)
    app.include_router(slides_api.router)
    app.include_router(video_api.router)
    app.include_router(package_api.router)
    app.include_router(models_api.router)
    app.include_router(share_api.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    static_dir = Path(__file__).parent / "presentation" / "web" / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
        logger.info("static frontend mounted at / (from %s)", static_dir)
    else:
        logger.warning("static/ directory not found at %s", static_dir)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
