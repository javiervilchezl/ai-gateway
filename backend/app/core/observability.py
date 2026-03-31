import logging

from app.core.config import settings


def get_langfuse_client():
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception as exc:
        logger = logging.getLogger("gateway.observability")
        logger.warning("Langfuse init failed: %s", exc)
        return None


def langfuse_trace_start(client, name: str, input_data: dict):
    if client is None:
        return None
    try:
        return client.trace(name=name, input=input_data)
    except Exception as exc:
        logging.getLogger("gateway.observability").warning(
            "Langfuse trace start failed: %s",
            exc,
        )
        return None


def langfuse_trace_end(trace, output_data: dict) -> None:
    if trace is None:
        return
    try:
        trace.update(output=output_data)
        trace.client.flush()
    except Exception as exc:
        logging.getLogger("gateway.observability").warning(
            "Langfuse trace end failed: %s",
            exc,
        )


def configure_observability() -> None:
    if settings.enable_openlit:
        try:
            import openlit

            openlit.init()
        except Exception as exc:
            logger = logging.getLogger("gateway.observability")
            logger.warning("OpenLIT init failed: %s", exc)


def estimate_cost(provider: str, prompt: str, completion: str) -> float:
    token_estimate = (len(prompt) + len(completion)) / 4
    if provider == "groq":
        # llama-3.1-8b-instant: ~$0.08 / 1M output tokens
        return round(token_estimate * 0.00000008, 8)
    # gpt-4o-mini: ~$0.60 / 1M output tokens
    return round(token_estimate * 0.00000060, 8)
