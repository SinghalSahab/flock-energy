from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.routes import cache, health, hierarchy, meters
from src.config import Settings, get_settings
from src.db.repository import SqliteRepository
from src.models.errors import APIException
from src.services.meter_service import MeterService
from src.services.portal_client import PortalClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("api")


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("Initializing Urja Meter API Service...")
        portal_client = PortalClient(
            base_url=cfg.portal_url,
            username=cfg.portal_username,
            password=cfg.portal_password,
            timeout=cfg.request_timeout_seconds,
        )
        repository = SqliteRepository(db_path=cfg.db_path)
        meter_service = MeterService(
            portal_client=portal_client,
            repository=repository,
            cache_ttl_seconds=cfg.cache_ttl_seconds,
        )

        app.state.settings = cfg
        app.state.portal_client = portal_client
        app.state.repository = repository
        app.state.meter_service = meter_service

        # Proactively warm cache if credentials are provided
        if cfg.portal_username and cfg.portal_password:
            try:
                logger.info("Warming cache from portal on startup...")
                meter_service.sync(force=True)
            except Exception as exc:
                logger.warning("Startup portal sync failed (will retry on demand): %s", exc)

        yield

        logger.info("Shutting down Urja Meter API Service...")

    app = FastAPI(
        title="Urja Meter Ops API Gateway",
        version="1.0.0",
        description="A clean, documented, high-performance API service in front of the legacy Urja Meter Ops utility portal.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Global Exception Handlers
    @app.exception_handler(APIException)
    async def handle_api_exception(request: Request, exc: APIException) -> JSONResponse:
        content = {
            "error": {
                "code": exc.code,
                "message": exc.message,
            }
        }
        if exc.details is not None:
            content["error"]["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Simplify validation errors into clean error structure
        errors = []
        for err in exc.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg')}")
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "BAD_REQUEST",
                    "message": "Invalid request query or parameters.",
                    "details": errors,
                }
            }
        )

    @app.exception_handler(Exception)
    async def handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected internal error occurred.",
                }
            }
        )

    # Attach Routers
    app.include_router(health.router)
    app.include_router(meters.router)
    app.include_router(hierarchy.router)
    app.include_router(cache.router)

    return app


app = create_app()
