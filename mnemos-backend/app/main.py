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
        description=(
            "Mnemos is a self-hosted facial recognition API. This service stores face embeddings "
            "in pgvector, supports multi-model detection (buffalo_s / buffalo_l from InsightFace), "
            "and exposes a JSON HTTP API for identification, person management, and re-indexing.\n\n"
            "**Authentication** — All `/api/v1/*` endpoints require an API key passed as the "
            "`X-API-Key` header. Keys are minted via the frontend pairing flow (`/system/pair`) "
            "or the admin UI. There are two permission levels: `Identify-Only` (can call "
            "`/identify` and read public data) and `Full-Admin` (can manage persons, keys, models, "
            "and the master key).\n\n"
            "**Realtime updates** — Subscribe to `ws://<host>/ws/events` for `inbox.new_face` "
            "and `inbox.bulk_changed` (live inbox updates) plus `reindex.*` / `warmup.*` events "
            "during model switches and warmups."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=[
            {"name": "health", "description": "Liveness and dependency checks."},
            {"name": "identify", "description": "Detect and recognize faces in uploaded images."},
            {
                "name": "faces",
                "description": "Manage face crops: assign to people, mark as non-face, ignore.",
            },
            {"name": "persons", "description": "CRUD for known people and their sample crops."},
            {"name": "models", "description": "Inspect, warmup, and switch the active InsightFace model."},
            {"name": "keys", "description": "Manage API keys (Full-Admin only)."},
            {"name": "system", "description": "Master key, pairing, and bootstrap (Full-Admin only)."},
            {"name": "crops", "description": "Fetch stored face crop JPEGs by crop UUID."},
        ],
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
