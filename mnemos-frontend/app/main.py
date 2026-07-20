from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import backend_proxy, health, pages, partials, ws_proxy, ws_target
from app.core.config import settings
from app.core.events import lifespan
from app.core.logging import configure_logging
from app.core.middleware import SessionMiddleware
from app.core.version import get_version


def create_app() -> FastAPI:
    configure_logging()
    log = logging.getLogger("mnemos.frontend.app")

    app = FastAPI(title="Mnemos Frontend", version=get_version(), lifespan=lifespan)

    app.add_middleware(SessionMiddleware)

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    app.include_router(health.router)
    app.include_router(pages.router)
    app.include_router(partials.router)
    app.include_router(ws_target.router)
    app.include_router(ws_proxy.router)
    app.include_router(backend_proxy.router, prefix="/backend")

    log.info("mnemos-frontend ready; listen=%s:%d", settings.listen_host, settings.listen_port)
    return app


app = create_app()
