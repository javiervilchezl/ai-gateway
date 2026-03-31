from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.auth import hash_password
from app.core.config import settings
from app.core.logging import configure_logging, request_logging_middleware
from app.core.observability import configure_observability
from app.core.rate_limit import rate_limiter
from app.db.database import SessionLocal, engine
from app.db.models import Base
from app.db.users import create_user, get_user_by_username
import logging
from contextlib import asynccontextmanager

configure_logging()
configure_observability()

_logger = logging.getLogger("gateway")


def _init_db() -> None:
    try:
        Base.metadata.create_all(bind=engine)
        if not settings.admin_default_password:
            return
        db = SessionLocal()
        try:
            if not get_user_by_username(db, settings.admin_default_username):
                create_user(
                    db,
                    settings.admin_default_username,
                    hash_password(settings.admin_default_password),
                )
        finally:
            db.close()
    except Exception as exc:
        _logger.warning("DB initialization skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.middleware("http")(request_logging_middleware)


@app.middleware("http")
async def trusted_ip_middleware(request: Request, call_next):
    trusted_ips = settings.trusted_client_ips_list
    if trusted_ips:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        remote_ip = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else ""
        )
        remote_ip = remote_ip or (
            request.client.host if request.client else ""
        )
        if remote_ip not in trusted_ips:
            return JSONResponse(
                status_code=403,
                content={"detail": "Client IP not allowed"},
            )
    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if settings.rate_limit_enabled:
        path = request.url.path
        is_login = path == "/api/v1/auth/login"
        is_api = path.startswith("/api/v1/")
        if is_login or is_api:
            forwarded_for = request.headers.get("x-forwarded-for", "")
            remote_ip = (
                forwarded_for.split(",")[0].strip()
                if forwarded_for
                else ""
            )
            remote_ip = remote_ip or (
                request.client.host if request.client else ""
            )
            bucket_id = f"{remote_ip}:{path}"
            if is_login:
                limit = settings.rate_limit_login_requests
                window = settings.rate_limit_login_window_seconds
            else:
                limit = settings.rate_limit_requests
                window = settings.rate_limit_window_seconds
            if rate_limiter.is_limited(
                bucket_id,
                max(1, limit),
                max(1, window),
            ):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                )
    return await call_next(request)


app.include_router(router)
cors_origins = settings.cors_allow_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=(cors_origins != ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
