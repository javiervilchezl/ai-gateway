import json
import logging
from time import perf_counter

from fastapi import Request

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def request_logging_middleware(request: Request, call_next):
    started_at = perf_counter()
    response = await call_next(request)
    elapsed = round((perf_counter() - started_at) * 1000, 2)
    logger = logging.getLogger("gateway.http")
    logger.info(
        json.dumps(
            {
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "latency_ms": elapsed,
            }
        )
    )
    return response
