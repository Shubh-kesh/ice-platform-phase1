"""
ICE backend entrypoint.

Wires together the FastAPI app: CORS, the versioned API router, global
exception handling, and structured startup/shutdown logging. Keep this
file thin — actual logic lives in api/, core/, models/, and schemas/.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.rate_limit import limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ice")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify the database is reachable before accepting traffic.
    # Failing fast here is much easier to debug than a 500 on first request.
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified — %s", settings.ENVIRONMENT)
    except Exception:
        logger.exception("Database connection failed at startup")
        raise

    yield

    # Shutdown: release the connection pool cleanly.
    await engine.dispose()
    logger.info("Database engine disposed — shutting down")


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Attach rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429,
    content={"detail": "Too many requests. Please try again later."}
))

# CORS — only the origins listed in BACKEND_CORS_ORIGINS may call this API
# from a browser. Credentials are allowed since auth uses httpOnly cookies
# for the refresh token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_timing_and_logging(request: Request, call_next):
    """Logs every request with latency. Cheap now, invaluable once you have
    15 sites hitting the API and something feels slow."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Returns a clean, consistent error shape instead of FastAPI's default
    verbose pydantic dump — easier for the React frontend to render."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation failed",
            "errors": [
                {"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"]}
                for err in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort catch-all so an unexpected error never leaks a stack
    trace to the client, but is still fully logged server-side."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again."},
    )


@app.get("/health", tags=["health"])
async def health_check():
    """Used by GCP load balancer / Cloud Run health checks and CI smoke tests."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}


app.include_router(api_router, prefix=settings.API_V1_STR)
