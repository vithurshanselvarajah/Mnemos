from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth,
    crops,
    faces,
    health,
    identify,
    keys,
    models_routes,
    persons,
    system,
    websocket,
)
from app.core.config import settings
from app.core.events import lifespan
from app.core.logging import configure_logging
from app.core.middleware import APIKeyAuthMiddleware
from app.core.version import get_version


def create_app() -> FastAPI:
    configure_logging()
    log = logging.getLogger("mnemos.app")

    app = FastAPI(
        title="Mnemos Backend",
        version=get_version(),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(APIKeyAuthMiddleware)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(identify.router, prefix="/api/v1")
    app.include_router(faces.router, prefix="/api/v1")
    app.include_router(persons.router, prefix="/api/v1")
    app.include_router(models_routes.router, prefix="/api/v1")
    app.include_router(keys.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")
    app.include_router(crops.router, prefix="/api/v1")
    app.include_router(websocket.router)

    log.info(
        "mnemos-backend ready; model=%s threshold=%.3f", settings.default_model, settings.default_threshold
    )
    return app


app = create_app()
