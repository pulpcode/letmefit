from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.request_id import RequestIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.mount(
        "/media",
        StaticFiles(directory=settings.media_upload_dir, check_dir=False),
        name="media",
    )
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/test", StaticFiles(directory=static_dir, html=True), name="test")
    return app


app = create_app()
