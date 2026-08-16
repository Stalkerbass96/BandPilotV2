"""FastAPI application factory.

Builds the ASGI app, wires up CORS, exception handlers, and route groups.
The factory pattern keeps configuration injection explicit and testable.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fretpilot.config import Settings, get_settings
from fretpilot.db.session import init_db

logger = logging.getLogger("fretpilot.app")


def _configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValueError)
    async def handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"code": 400, "data": None, "message": str(exc)},
        )


def _register_routes(app: FastAPI) -> None:
    from fretpilot.api.routes import auth, byok, exports, projects, tunings

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(byok.router, prefix="/api/byok", tags=["byok"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(exports.router, prefix="/api/projects", tags=["exports"])
    app.include_router(tunings.router, prefix="/api/tunings", tags=["tunings"])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("Starting %s (debug=%s)", settings.app_name, settings.debug)
    init_db(settings.database_url)
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    _configure_logging(settings.debug)

    app = FastAPI(
        title=settings.app_name,
        version="2.0.0",
        description="Repair AI-generated guitar MIDI into playable, notatable output.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)
    _register_routes(app)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, object]:
        return {"code": 0, "data": {"status": "ok"}, "message": "ok"}

    return app


__all__ = ["create_app"]
