from math import floor

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import AuthError, create_access_token, decode_access_token, verify_password
from app.clients.services import ServiceClient
from app.core.config import settings
from app.db.database import get_db
from app.db.users import get_user_by_username
from app.providers.factory import get_provider
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.orchestrator import OrchestratorService

router = APIRouter(prefix="/api/v1")


def get_orchestrator_service() -> OrchestratorService:
    return OrchestratorService(
        service_client=ServiceClient(),
        provider=get_provider(),
    )


def verify_gateway_api_key(
    api_key: str | None = Header(
        default=None,
        alias=settings.gateway_api_key_header,
    ),
) -> None:
    if not settings.gateway_api_key:
        return
    if api_key == settings.gateway_api_key:
        return
    raise HTTPException(status_code=401, detail="Missing or invalid API key")


def verify_jwt_bearer(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    if not settings.auth_require_jwt:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header",
        )
    try:
        decode_access_token(parts[1])
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = get_user_by_username(db, payload.username)
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        token = create_access_token(payload.username)
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TokenResponse(
        access_token=token,
        expires_in=floor(settings.jwt_access_token_expire_minutes * 60),
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    _: None = Depends(verify_gateway_api_key),
    __: None = Depends(verify_jwt_bearer),
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> AnalyzeResponse:
    try:
        return await service.analyze(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        detail = _extract_detail(exc)
        raise HTTPException(
            status_code=_downstream_status_code(exc),
            detail=detail,
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503, detail=f"Service unavailable: {exc}"
        ) from exc


@router.post("/analyze-pdf-file", response_model=AnalyzeResponse)
async def analyze_pdf_file(
    file: UploadFile = File(...),
    _: None = Depends(verify_gateway_api_key),
    __: None = Depends(verify_jwt_bearer),
    service: OrchestratorService = Depends(get_orchestrator_service),
) -> AnalyzeResponse:
    supported_types = {"application/pdf", "application/octet-stream"}
    if file.content_type not in supported_types:
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported",
        )
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="PDF file is empty")
    try:
        return await service.analyze_pdf_bytes(
            file.filename or "upload.pdf",
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        detail = _extract_detail(exc)
        raise HTTPException(
            status_code=_downstream_status_code(exc),
            detail=detail,
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503, detail=f"Service unavailable: {exc}"
        ) from exc


def _extract_detail(exc: httpx.HTTPStatusError) -> str:
    """Extract the detail message from a downstream HTTP error response."""
    try:
        payload = exc.response.json()
        if isinstance(payload.get("detail"), str):
            return payload["detail"]
    except Exception:
        pass
    return f"Downstream service error (HTTP {exc.response.status_code})"


def _downstream_status_code(exc: httpx.HTTPStatusError) -> int:
    status_code = exc.response.status_code
    if 400 <= status_code < 500:
        return status_code
    return 502
