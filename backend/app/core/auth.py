from datetime import UTC, datetime, timedelta

import jwt
import bcrypt

from app.core.config import settings


class AuthError(Exception):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(subject: str) -> str:
    if not settings.jwt_secret_key:
        raise AuthError("JWT secret key is not configured")
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    if not settings.jwt_secret_key:
        raise AuthError("JWT secret key is not configured")
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token") from exc
    if not payload.get("sub"):
        raise AuthError("Invalid token payload")
    return payload
