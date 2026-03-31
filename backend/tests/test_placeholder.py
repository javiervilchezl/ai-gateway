import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Request, Response
from fastapi.testclient import TestClient

import app
import app.api
import app.clients
import app.core
import app.db
import app.providers
import app.schemas
import app.services
from app.api.routes import get_orchestrator_service
from app.clients.services import ServiceClient
from app.core.auth import AuthError, create_access_token, decode_access_token
from app.core.config import settings
from app.core.logging import request_logging_middleware
from app.core.observability import (
    configure_observability,
    estimate_cost,
    get_langfuse_client,
    langfuse_trace_end,
    langfuse_trace_start,
)
from app.core.rate_limit import rate_limiter
from app.main import app as fastapi_app
from app.providers.base import LLMProvider
from app.providers.factory import get_provider
from app.providers.groq_provider import GroqProvider
from app.providers.openai_provider import OpenAIProvider
from app.schemas.analyze import AnalyzeRequest
from app.services.orchestrator import OrchestratorService


class DummyProvider(LLMProvider):
    async def generate(self, prompt: str, system_prompt: str) -> str:
        return await super().generate(prompt, system_prompt)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeHTTPClient:
    def __init__(self) -> None:
        self.calls = []

    async def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("analyze-pdf"):
            return FakeResponse({"summary": "pdf", "topics": ["ops"]})
        if url.endswith("classify"):
            return FakeResponse({"label": "complaint", "confidence": 0.88})
        return FakeResponse(
            {
                "intent": "customer_support",
                "entities": {"product": "subscription"},
            }
        )


class FakeProvider:
    def __init__(self, route: str = "both") -> None:
        self.route = route
        self.prompts = []

    async def generate(self, prompt: str, system_prompt: str) -> str:
        self.prompts.append((prompt, system_prompt))
        return '{"route":"%s"}' % self.route


class StubOrchestrator:
    async def analyze(self, payload: AnalyzeRequest):
        if payload.content == "error":
            raise ValueError("bad input")
        return {
            "input_type": payload.input_type,
            "summary": None,
            "topics": [],
            "category": "complaint",
            "confidence": 0.9,
            "intent": "customer_support",
            "entities": {},
            "metadata": {
                "provider": "openai",
                "latency_ms": 1.0,
                "prompt": "p",
                "cost_estimate": 0.01,
            },
        }

    async def analyze_pdf_bytes(self, file_name: str, payload: bytes):
        if not payload:
            raise ValueError("empty")
        return {
            "input_type": "pdf",
            "summary": f"{file_name}-summary",
            "topics": ["finance"],
            "category": "sales",
            "confidence": 0.89,
            "intent": "Document review",
            "entities": {},
            "metadata": {
                "provider": "openai",
                "latency_ms": 1.0,
                "prompt": "p",
                "cost_estimate": 0.01,
            },
        }


class StubOrchestratorPDFError(StubOrchestrator):
    async def analyze_pdf_bytes(self, file_name: str, payload: bytes):
        raise ValueError("pdf-error")


class StubOrchestratorHTTPError(StubOrchestrator):
    def __init__(
        self,
        status_code: int = 422,
        detail: str | None = "No readable text found in PDF",
    ) -> None:
        import httpx as _httpx
        request = _httpx.Request("POST", "http://pdf-service/analyze-pdf")
        body = f'{{"detail":"{detail}"}}' if detail else '{"other":"x"}'
        response = _httpx.Response(status_code, text=body, request=request)
        self._exc = _httpx.HTTPStatusError(
            f"HTTP {status_code}", request=request, response=response
        )

    async def analyze_pdf_bytes(self, file_name: str, payload: bytes):
        raise self._exc

    async def analyze(self, payload):
        raise self._exc


class StubOrchestratorConnectError(StubOrchestrator):
    async def analyze_pdf_bytes(self, file_name: str, payload: bytes):
        import httpx as _httpx
        raise _httpx.ConnectError("Connection refused")

    async def analyze(self, payload):
        import httpx as _httpx
        raise _httpx.ConnectError("Connection refused")


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    fastapi_app.dependency_overrides.clear()
    rate_limiter.clear()
    settings.auth_require_jwt = False
    settings.gateway_api_key = ""
    settings.trusted_client_ips = ""
    settings.rate_limit_enabled = False
    yield
    fastapi_app.dependency_overrides.clear()
    rate_limiter.clear()
    settings.auth_require_jwt = False
    settings.gateway_api_key = ""
    settings.trusted_client_ips = ""
    settings.rate_limit_enabled = False


def test_package_exports_are_importable() -> None:
    assert app.__all__ == []
    assert app.api.__all__ == []
    assert app.clients.__all__ == []
    assert app.core.__all__ == []
    assert app.db.__all__ == []
    assert app.providers.__all__ == []
    assert app.schemas.__all__ == []
    assert app.services.__all__ == []


@pytest.mark.asyncio
async def test_base_provider_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await DummyProvider().generate("prompt", "system")


def test_get_provider_returns_openai(monkeypatch) -> None:
    from app.providers import factory

    monkeypatch.setattr(factory.settings, "provider", "openai")
    monkeypatch.setattr(factory, "OpenAIProvider", lambda: "openai")
    assert get_provider() == "openai"


def test_get_provider_returns_groq(monkeypatch) -> None:
    from app.providers import factory

    monkeypatch.setattr(factory.settings, "provider", "groq")
    monkeypatch.setattr(factory, "GroqProvider", lambda: "groq")
    assert get_provider() == "groq"


def test_get_orchestrator_service(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.ServiceClient", lambda: "client")
    monkeypatch.setattr("app.api.routes.get_provider", lambda: "provider")

    service = get_orchestrator_service()

    assert service.service_client == "client"
    assert service.provider == "provider"


@pytest.mark.asyncio
async def test_openai_provider_generate_with_helicone(monkeypatch) -> None:
    captured = {}

    class FakeResponses:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="gateway-openai")

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setattr(
        "app.providers.openai_provider.AsyncOpenAI",
        FakeClient,
    )
    monkeypatch.setattr(
        "app.providers.openai_provider.settings.helicone_api_key",
        "helicone-key",
    )
    provider = OpenAIProvider()
    result = await provider.generate("hello", "system")

    assert result == "gateway-openai"
    assert captured["extra_headers"]["Helicone-Auth"] == "Bearer helicone-key"


@pytest.mark.asyncio
async def test_groq_provider_generate(monkeypatch) -> None:
    class FakeCompletions:
        async def create(self, **kwargs):
            message = SimpleNamespace(content="gateway-groq")
            choice = SimpleNamespace(message=message)
            return SimpleNamespace(choices=[choice])

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(
        "app.providers.groq_provider.import_module",
        lambda _: SimpleNamespace(AsyncGroq=FakeClient),
    )
    provider = GroqProvider()
    assert await provider.generate("hello", "system") == "gateway-groq"


@pytest.mark.asyncio
async def test_request_logging_middleware() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "root_path": "",
    }
    request = Request(scope)

    async def call_next(_: Request) -> Response:
        return Response(status_code=204)

    response = await request_logging_middleware(request, call_next)
    assert response.status_code == 204


def test_estimate_cost_returns_value() -> None:
    assert estimate_cost("openai", "abcd", "efgh") > 0
    assert estimate_cost("groq", "abcd", "efgh") > 0


def test_get_langfuse_client_without_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_public_key",
        "",
    )
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_secret_key",
        "",
    )
    assert get_langfuse_client() is None


def test_get_langfuse_client_with_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_public_key",
        "pk",
    )
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_secret_key",
        "sk",
    )
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_host",
        "host",
    )

    class FakeLangfuse:
        def __init__(
            self,
            public_key: str,
            secret_key: str,
            host: str,
        ) -> None:
            self.public_key = public_key
            self.secret_key = secret_key
            self.host = host

    monkeypatch.setitem(
        sys.modules,
        "langfuse",
        SimpleNamespace(Langfuse=FakeLangfuse),
    )
    client = get_langfuse_client()
    assert client.public_key == "pk"
    assert client.secret_key == "sk"
    assert client.host == "host"


def test_get_langfuse_client_handles_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_public_key",
        "pk",
    )
    monkeypatch.setattr(
        "app.core.observability.settings.langfuse_secret_key",
        "sk",
    )

    class FailingLangfuse:
        def __init__(self, **kwargs) -> None:
            raise RuntimeError("langfuse-boom")

    monkeypatch.setitem(
        sys.modules,
        "langfuse",
        SimpleNamespace(Langfuse=FailingLangfuse),
    )
    assert get_langfuse_client() is None


def test_langfuse_trace_helpers() -> None:
    class FakeTrace:
        def __init__(self) -> None:
            self.updated = None
            self.client = SimpleNamespace(flush=lambda: None)

        def update(self, output: dict) -> None:
            self.updated = output

    class FakeClient:
        def trace(self, name: str, input: dict):
            assert name == "trace"
            assert input["ok"] is True
            return FakeTrace()

    trace = langfuse_trace_start(FakeClient(), "trace", {"ok": True})
    langfuse_trace_end(trace, {"done": True})
    assert trace.updated == {"done": True}


def test_langfuse_trace_start_none_client() -> None:
    assert langfuse_trace_start(None, "trace", {"ok": True}) is None


def test_langfuse_trace_start_handles_exception() -> None:
    class FailingClient:
        def trace(self, **kwargs):
            raise RuntimeError("trace-boom")

    assert langfuse_trace_start(FailingClient(), "trace", {"ok": True}) is None


def test_langfuse_trace_end_none_trace() -> None:
    langfuse_trace_end(None, {"ok": True})


def test_langfuse_trace_end_handles_exception() -> None:
    class FailingTrace:
        def update(self, output: dict) -> None:
            raise RuntimeError("update-boom")

        client = SimpleNamespace(flush=lambda: None)

    langfuse_trace_end(FailingTrace(), {"ok": True})


def test_configure_observability_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.observability.settings.enable_openlit",
        False,
    )
    configure_observability()


def test_configure_observability_enabled(monkeypatch) -> None:
    state = {"called": False}

    class FakeOpenLIT:
        @staticmethod
        def init() -> None:
            state["called"] = True

    monkeypatch.setattr("app.core.observability.settings.enable_openlit", True)
    monkeypatch.setitem(sys.modules, "openlit", FakeOpenLIT)
    configure_observability()
    assert state["called"] is True


def test_configure_observability_handles_exception(monkeypatch) -> None:
    class FailingOpenLIT:
        @staticmethod
        def init() -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr("app.core.observability.settings.enable_openlit", True)
    monkeypatch.setitem(sys.modules, "openlit", FailingOpenLIT)
    configure_observability()


@pytest.mark.asyncio
async def test_service_client_calls_services(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"pdf")
    fake_client = FakeHTTPClient()
    service_client = ServiceClient()
    service_client.client = fake_client

    pdf_result = await service_client.analyze_pdf(str(pdf_path))
    classify_result = await service_client.classify(
        "refund",
        ["sales", "complaint"],
    )
    intent_result = await service_client.detect_intent("refund")

    assert pdf_result["summary"] == "pdf"
    assert classify_result["label"] == "complaint"
    assert intent_result["intent"] == "customer_support"
    assert len(fake_client.calls) == 3


@pytest.mark.asyncio
async def test_service_client_analyze_pdf_bytes() -> None:
    fake_client = FakeHTTPClient()
    service_client = ServiceClient()
    service_client.client = fake_client

    result = await service_client.analyze_pdf_bytes("doc.pdf", b"pdf")

    assert result["summary"] == "pdf"


@pytest.mark.asyncio
async def test_service_client_sends_internal_key_header(monkeypatch) -> None:
    fake_client = FakeHTTPClient()
    service_client = ServiceClient()
    service_client.client = fake_client
    monkeypatch.setattr(settings, "internal_service_api_key", "svc-key")
    monkeypatch.setattr(
        settings,
        "internal_service_api_key_header",
        "X-Service-API-Key",
    )

    await service_client.classify("refund", ["sales", "complaint"])

    _, kwargs = fake_client.calls[0]
    assert kwargs["headers"]["X-Service-API-Key"] == "svc-key"


@pytest.mark.asyncio
async def test_orchestrator_pdf_requires_path() -> None:
    service = OrchestratorService(ServiceClient(), FakeProvider())
    with pytest.raises(ValueError):
        await service.analyze(AnalyzeRequest(input_type="pdf", content=None))


@pytest.mark.asyncio
async def test_orchestrator_pdf_flow() -> None:
    class PDFOnlyClient:
        async def analyze_pdf(self, file_path: str) -> dict:
            assert file_path == "document.pdf"
            return {
                "summary": "pdf",
                "topics": ["ops"],
                "text": "Sample PDF text content",
            }

        async def classify(self, text: str, labels: list) -> dict:
            return {"label": "sales", "confidence": 0.85}

        async def detect_intent(self, text: str) -> dict:
            return {
                "intent": "Document review",
                "entities": {},
            }

    service = OrchestratorService(PDFOnlyClient(), FakeProvider())
    result = await service.analyze(
        AnalyzeRequest(input_type="pdf", content="document.pdf")
    )

    assert result.input_type == "pdf"
    assert result.summary == "pdf"
    assert result.topics == ["ops"]
    assert result.category == "sales"
    assert result.confidence == 0.85
    assert result.intent == "Document review"


@pytest.mark.asyncio
async def test_orchestrator_pdf_upload_flow() -> None:
    class PDFOnlyClient:
        async def analyze_pdf_bytes(
            self,
            file_name: str,
            payload: bytes,
        ) -> dict:
            assert file_name == "upload.pdf"
            assert payload == b"pdf"
            return {
                "summary": "pdf-upload",
                "topics": ["ops"],
                "text": "PDF upload content",
            }

        async def classify(self, text: str, labels: list) -> dict:
            return {"label": "complaint", "confidence": 0.92}

        async def detect_intent(self, text: str) -> dict:
            return {
                "intent": "Support request",
                "entities": {},
            }

    service = OrchestratorService(PDFOnlyClient(), FakeProvider())
    result = await service.analyze_pdf_bytes("upload.pdf", b"pdf")

    assert result.input_type == "pdf"
    assert result.summary == "pdf-upload"
    assert result.topics == ["ops"]
    assert result.category == "complaint"
    assert result.confidence == 0.92
    assert result.intent == "Support request"


@pytest.mark.asyncio
async def test_orchestrator_text_auto_both() -> None:
    fake_http = FakeHTTPClient()
    client = ServiceClient()
    client.client = fake_http
    provider = FakeProvider(route="both")
    service = OrchestratorService(client, provider)
    result = await service.analyze(
        AnalyzeRequest(input_type="text", content="refund", mode="auto")
    )
    assert result.category == "complaint"
    assert result.intent == "customer_support"
    assert result.entities == {"product": "subscription"}


@pytest.mark.asyncio
async def test_orchestrator_text_classify_only() -> None:
    fake_http = FakeHTTPClient()
    client = ServiceClient()
    client.client = fake_http
    service = OrchestratorService(client, FakeProvider(route="intent"))
    result = await service.analyze(
        AnalyzeRequest(input_type="text", content="refund", mode="classify")
    )
    assert result.category == "complaint"
    assert result.intent is None


@pytest.mark.asyncio
async def test_orchestrator_text_intent_only() -> None:
    fake_http = FakeHTTPClient()
    client = ServiceClient()
    client.client = fake_http
    service = OrchestratorService(client, FakeProvider(route="classify"))
    result = await service.analyze(
        AnalyzeRequest(input_type="text", content="refund", mode="intent")
    )
    assert result.category is None
    assert result.intent == "customer_support"


@pytest.mark.asyncio
async def test_orchestrator_skips_routing_when_mode_is_explicit() -> None:
    class FailIfCalledProvider:
        async def generate(self, prompt: str, system_prompt: str) -> str:
            raise AssertionError("routing provider should not be called")

    fake_http = FakeHTTPClient()
    client = ServiceClient()
    client.client = fake_http
    service = OrchestratorService(client, FailIfCalledProvider())

    result = await service.analyze(
        AnalyzeRequest(input_type="text", content="refund", mode="both")
    )

    assert result.category == "complaint"
    assert result.intent == "customer_support"


@pytest.mark.asyncio
async def test_orchestrator_auto_route_truncates_long_text() -> None:
    captured = {}

    class CapturingProvider:
        async def generate(self, prompt: str, system_prompt: str) -> str:
            captured["prompt"] = prompt
            return '{"route":"both"}'

    fake_http = FakeHTTPClient()
    client = ServiceClient()
    client.client = fake_http
    service = OrchestratorService(client, CapturingProvider())
    long_text = ("refund request invoice support " * 1000) + "tail"

    result = await service.analyze(
        AnalyzeRequest(input_type="text", content=long_text, mode="auto")
    )

    assert result.category == "complaint"
    assert result.intent == "customer_support"
    assert "[truncated]" in captured["prompt"]
    assert "tail" not in captured["prompt"]


@pytest.mark.asyncio
async def test_orchestrator_text_both_degrades_when_intent_fails() -> None:
    class PartialFailureClient:
        async def classify(self, text: str, labels: list[str]) -> dict:
            return {"label": "complaint", "confidence": 0.88}

        async def detect_intent(self, text: str) -> dict:
            request = httpx.Request(
                "POST",
                "http://intent-service/detect-intent",
            )
            response = httpx.Response(
                502,
                json={"detail": "bad intent"},
                request=request,
            )
            raise httpx.HTTPStatusError(
                "bad intent",
                request=request,
                response=response,
            )

    service = OrchestratorService(
        PartialFailureClient(),
        FakeProvider(route="both"),
    )
    result = await service.analyze(
        AnalyzeRequest(input_type="text", content="refund", mode="both")
    )

    assert result.category == "complaint"
    assert result.confidence == 0.88
    assert result.intent is None
    assert result.entities == {}


@pytest.mark.asyncio
async def test_orchestrator_pdf_upload_degrades_when_classify_fails() -> None:
    class PartialFailureClient:
        async def analyze_pdf_bytes(
            self,
            file_name: str,
            payload: bytes,
        ) -> dict:
            return {
                "summary": "pdf-upload",
                "topics": ["ops"],
                "text": "PDF upload content",
            }

        async def classify(self, text: str, labels: list[str]) -> dict:
            request = httpx.Request(
                "POST",
                "http://classifier-service/classify",
            )
            response = httpx.Response(
                502,
                json={"detail": "bad classify"},
                request=request,
            )
            raise httpx.HTTPStatusError(
                "bad classify",
                request=request,
                response=response,
            )

        async def detect_intent(self, text: str) -> dict:
            return {"intent": "Support request", "entities": {}}

    service = OrchestratorService(PartialFailureClient(), FakeProvider())
    result = await service.analyze_pdf_bytes("upload.pdf", b"pdf")

    assert result.summary == "pdf-upload"
    assert result.topics == ["ops"]
    assert result.category is None
    assert result.confidence is None
    assert result.intent == "Support request"


def test_health_endpoint() -> None:
    client = TestClient(fastapi_app)
    response = client.get("/health")
    assert response.status_code == 200


def test_api_analyze_success() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
    )
    assert response.status_code == 200
    assert response.json()["category"] == "complaint"


def test_api_analyze_requires_gateway_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gateway_api_key", "front-key")
    monkeypatch.setattr(settings, "gateway_api_key_header", "X-API-Key")
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)

    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
    )
    assert response.status_code == 401


def test_api_analyze_accepts_gateway_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "gateway_api_key", "front-key")
    monkeypatch.setattr(settings, "gateway_api_key_header", "X-API-Key")
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)

    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
        headers={"X-API-Key": "front-key"},
    )
    assert response.status_code == 200


def test_api_analyze_bad_request() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "error", "mode": "both"},
    )
    assert response.status_code == 400


def test_api_analyze_pdf_file_success() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.pdf", b"pdf", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["summary"] == "report.pdf-summary"
    assert response.json()["category"] == "sales"
    assert response.json()["confidence"] == 0.89
    assert response.json()["intent"] == "Document review"


def test_api_analyze_pdf_file_rejects_invalid_type() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.txt", b"txt", "text/plain")},
    )
    assert response.status_code == 400


def test_api_analyze_pdf_file_rejects_empty_payload() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestrator
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_api_analyze_pdf_file_bad_request_from_service() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        StubOrchestratorPDFError
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.pdf", b"pdf", "application/pdf")},
    )
    assert response.status_code == 400


def test_api_analyze_pdf_file_downstream_http_error() -> None:
    """pdf-service returns 422 and gateway preserves that client error."""
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        lambda: StubOrchestratorHTTPError(422, "No readable text found in PDF")
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.pdf", b"pdf", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "No readable text found in PDF"


def test_api_analyze_pdf_file_downstream_http_error_no_detail() -> None:
    """No detail in downstream error â†’ gateway returns 502 generic."""
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        lambda: StubOrchestratorHTTPError(500, None)
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.pdf", b"pdf", "application/pdf")},
    )
    assert response.status_code == 502
    assert "500" in response.json()["detail"]


def test_api_analyze_pdf_file_connect_error() -> None:
    """Connection to pdf-service fails â†’ gateway returns 503."""
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        lambda: StubOrchestratorConnectError()
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze-pdf-file",
        files={"file": ("report.pdf", b"pdf", "application/pdf")},
    )
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_api_analyze_downstream_http_error() -> None:
    """analyze endpoint preserves downstream 4xx errors."""
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        lambda: StubOrchestratorHTTPError(422, "bad label")
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "hi", "mode": "both"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "bad label"


def test_api_analyze_connect_error() -> None:
    fastapi_app.dependency_overrides[get_orchestrator_service] = (
        lambda: StubOrchestratorConnectError()
    )
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "hi", "mode": "both"},
    )
    assert response.status_code == 503


def test_extract_detail_non_json_response() -> None:
    """_extract_detail: falls back when body is not JSON."""
    from app.api.routes import _extract_detail

    req = httpx.Request("POST", "http://svc/path")
    resp = httpx.Response(503, text="Service Unavailable", request=req)
    exc = httpx.HTTPStatusError("503", request=req, response=resp)

    detail = _extract_detail(exc)
    assert "503" in detail


def test_downstream_status_code_preserves_client_errors() -> None:
    from app.api.routes import _downstream_status_code

    request = httpx.Request("POST", "http://svc/path")
    response = httpx.Response(422, json={"detail": "bad pdf"}, request=request)
    exc = httpx.HTTPStatusError("422", request=request, response=response)

    assert _downstream_status_code(exc) == 422


def test_downstream_status_code_maps_server_errors_to_bad_gateway() -> None:
    from app.api.routes import _downstream_status_code

    request = httpx.Request("POST", "http://svc/path")
    response = httpx.Response(500, text="boom", request=request)
    exc = httpx.HTTPStatusError("500", request=request, response=response)

    assert _downstream_status_code(exc) == 502


def test_trusted_ip_middleware_blocks_unknown_ip(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_client_ips", "10.10.10.10")
    client = TestClient(fastapi_app)

    response = client.get("/health")

    assert response.status_code == 403


def test_trusted_ip_middleware_allows_known_forwarded_ip(monkeypatch) -> None:
    monkeypatch.setattr(settings, "trusted_client_ips", "10.10.10.10")
    client = TestClient(fastapi_app)

    response = client.get(
        "/health",
        headers={"x-forwarded-for": "10.10.10.10"},
    )

    assert response.status_code == 200


def test_config_csv_list_properties(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "cors_allow_origins",
        "http://localhost:5173, https://frontend.local",
    )
    monkeypatch.setattr(
        settings,
        "trusted_client_ips",
        "127.0.0.1,10.0.0.9",
    )

    assert settings.cors_allow_origins_list == [
        "http://localhost:5173",
        "https://frontend.local",
    ]
    assert settings.trusted_client_ips_list == ["127.0.0.1", "10.0.0.9"]


def test_jwt_create_and_decode(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings, "jwt_access_token_expire_minutes", 5)

    token = create_access_token("admin")
    payload = decode_access_token(token)

    assert payload["sub"] == "admin"


def test_jwt_create_requires_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "")

    with pytest.raises(AuthError):
        create_access_token("admin")


def test_jwt_decode_rejects_invalid(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")

    with pytest.raises(AuthError):
        decode_access_token("bad.token.value")


def test_api_login_success(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.core.auth import hash_password
    from app.db.database import get_db
    from app.db.models import User as DBUser

    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "jwt_access_token_expire_minutes", 30)

    mock_user = DBUser()
    mock_user.username = "admin"
    mock_user.hashed_password = hash_password("pass")

    def mock_get_db():
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = mock_get_db

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "pass"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["expires_in"] == 1800


def test_api_login_invalid_credentials(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.core.auth import hash_password
    from app.db.database import get_db
    from app.db.models import User as DBUser

    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")

    mock_user = DBUser()
    mock_user.username = "admin"
    mock_user.hashed_password = hash_password("pass")

    def mock_get_db():
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = mock_get_db

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert response.status_code == 401


def test_api_login_not_configured(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.db.database import get_db

    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")

    def mock_get_db():
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = mock_get_db

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "unknown", "password": "pass"},
    )

    assert response.status_code == 401


def test_api_analyze_requires_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_require_jwt", True)
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "gateway_api_key", "")
    fastapi_app.dependency_overrides[
        get_orchestrator_service
    ] = StubOrchestrator

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
    )

    assert response.status_code == 401


def test_api_analyze_accepts_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_require_jwt", True)
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "gateway_api_key", "")
    token = create_access_token("admin")
    fastapi_app.dependency_overrides[
        get_orchestrator_service
    ] = StubOrchestrator

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_api_analyze_rejects_invalid_bearer_header(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_require_jwt", True)
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "gateway_api_key", "")
    fastapi_app.dependency_overrides[
        get_orchestrator_service
    ] = StubOrchestrator

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
        headers={"Authorization": "Token abc"},
    )

    assert response.status_code == 401


def test_rate_limit_blocks_repeated_analyze_requests(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_require_jwt", False)
    monkeypatch.setattr(settings, "gateway_api_key", "")
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    fastapi_app.dependency_overrides[
        get_orchestrator_service
    ] = StubOrchestrator

    client = TestClient(fastapi_app)
    response_1 = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
    )
    response_2 = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
    )

    assert response_1.status_code == 200
    assert response_2.status_code == 429


def test_rate_limit_blocks_repeated_login_requests(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_login_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_login_window_seconds", 60)
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")

    from unittest.mock import MagicMock

    from app.core.auth import hash_password
    from app.db.database import get_db
    from app.db.models import User as DBUser

    mock_user = DBUser()
    mock_user.username = "admin"
    mock_user.hashed_password = hash_password("pass")

    def mock_get_db():
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = mock_get_db

    client = TestClient(fastapi_app)
    response_1 = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "pass"},
    )
    response_2 = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "pass"},
    )

    assert response_1.status_code == 200
    assert response_2.status_code == 429


def test_api_analyze_rejects_invalid_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_require_jwt", True)
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "gateway_api_key", "")
    fastapi_app.dependency_overrides[
        get_orchestrator_service
    ] = StubOrchestrator

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/analyze",
        json={"input_type": "text", "content": "refund", "mode": "both"},
        headers={"Authorization": "Bearer invalid.token"},
    )

    assert response.status_code == 401


def test_api_login_fails_without_jwt_secret(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from app.core.auth import hash_password
    from app.db.database import get_db
    from app.db.models import User as DBUser

    monkeypatch.setattr(settings, "jwt_secret_key", "")

    mock_user = DBUser()
    mock_user.username = "admin"
    mock_user.hashed_password = hash_password("pass")

    def mock_get_db():
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_user
        yield mock_db

    fastapi_app.dependency_overrides[get_db] = mock_get_db

    client = TestClient(fastapi_app)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "pass"},
    )

    assert response.status_code == 503


def test_jwt_decode_requires_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "")

    with pytest.raises(AuthError):
        decode_access_token("anything")


def test_jwt_decode_rejects_missing_subject(monkeypatch) -> None:
    monkeypatch.setattr(settings, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")
    token = __import__("jwt").encode(
        {"iat": 1, "exp": 9999999999},
        "test-secret",
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        decode_access_token(token)


def test_service_client_internal_headers_empty(monkeypatch) -> None:
    monkeypatch.setattr(settings, "internal_service_api_key", "")
    service_client = ServiceClient()

    try:
        assert service_client._internal_headers() == {}
    finally:
        import asyncio

        asyncio.run(service_client.client.aclose())


def test_rate_limiter_cleans_expired_bucket(monkeypatch) -> None:
    module = __import__("app.core.rate_limit", fromlist=["RateLimiter"])
    limiter = module.RateLimiter()
    sequence = iter([0.0, 1.0, 62.0])
    monkeypatch.setattr(
        "app.core.rate_limit.monotonic",
        lambda: next(sequence),
    )

    assert limiter.is_limited("k", 2, 60) is False
    assert limiter.is_limited("k", 2, 60) is False
    assert limiter.is_limited("k", 2, 60) is False


# ── auth: hash_password / verify_password ────────────────────────────────────

def test_hash_and_verify_password() -> None:
    from app.core.auth import hash_password, verify_password

    hashed = hash_password("mysecret")
    assert isinstance(hashed, str)
    assert verify_password("mysecret", hashed) is True
    assert verify_password("wrong", hashed) is False


# ── db.database: get_db generator ────────────────────────────────────────────

def test_get_db_yields_session_and_closes() -> None:
    from unittest.mock import MagicMock, patch

    import app.db.database as db_module

    mock_session = MagicMock()
    with patch.object(db_module, "SessionLocal", return_value=mock_session):
        gen = db_module.get_db()
        session = next(gen)
        assert session is mock_session
        try:
            next(gen)
        except StopIteration:
            pass
    mock_session.close.assert_called_once()


# ── db.models: User ORM model ─────────────────────────────────────────────────

def test_user_model_attributes() -> None:
    from app.db.models import User

    user = User(username="testuser", hashed_password="hashed")
    assert user.username == "testuser"
    assert user.hashed_password == "hashed"


# ── db.users: CRUD helpers ────────────────────────────────────────────────────

def test_get_user_by_username_found() -> None:
    from unittest.mock import MagicMock

    from app.db.models import User
    from app.db.users import get_user_by_username

    expected = User(username="admin", hashed_password="h")
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = expected

    result = get_user_by_username(mock_db, "admin")
    assert result is expected


def test_get_user_by_username_not_found() -> None:
    from unittest.mock import MagicMock

    from app.db.users import get_user_by_username

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    assert get_user_by_username(mock_db, "nobody") is None


def test_create_user() -> None:
    from unittest.mock import MagicMock

    from app.db.users import create_user

    mock_db = MagicMock()
    result = create_user(mock_db, "newuser", "hashed_pw")

    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()
    assert result.username == "newuser"
    assert result.hashed_password == "hashed_pw"


# ── main._init_db: lifespan DB seeding ───────────────────────────────────────

def test_init_db_creates_admin_when_not_exists(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    mock_base = MagicMock()
    mock_session = MagicMock()
    created: dict = {}

    monkeypatch.setattr(main_module, "Base", mock_base)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: mock_session)
    monkeypatch.setattr(main_module, "get_user_by_username", lambda db, u: None)
    monkeypatch.setattr(
        main_module,
        "create_user",
        lambda db, u, p: created.update({"user": u, "pw": p}),
    )
    monkeypatch.setattr(settings, "admin_default_password", "adminpass")
    monkeypatch.setattr(settings, "admin_default_username", "admin")

    main_module._init_db()

    assert created.get("user") == "admin"
    mock_session.close.assert_called_once()


def test_init_db_skips_if_no_default_password(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    mock_base = MagicMock()
    session_called: dict = {}

    monkeypatch.setattr(main_module, "Base", mock_base)
    monkeypatch.setattr(
        main_module,
        "SessionLocal",
        lambda: session_called.update({"called": True}) or MagicMock(),  # type: ignore[return-value]
    )
    monkeypatch.setattr(settings, "admin_default_password", "")

    main_module._init_db()

    assert "called" not in session_called


def test_init_db_skips_create_if_admin_exists(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module
    from app.db.models import User

    existing = User(username="admin", hashed_password="h")
    mock_base = MagicMock()
    mock_session = MagicMock()
    create_called: dict = {}

    monkeypatch.setattr(main_module, "Base", mock_base)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: mock_session)
    monkeypatch.setattr(main_module, "get_user_by_username", lambda db, u: existing)
    monkeypatch.setattr(
        main_module,
        "create_user",
        lambda db, u, p: create_called.update({"called": True}),
    )
    monkeypatch.setattr(settings, "admin_default_password", "pass")
    monkeypatch.setattr(settings, "admin_default_username", "admin")

    main_module._init_db()

    assert "called" not in create_called
    mock_session.close.assert_called_once()


def test_init_db_handles_exception_gracefully(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    bad_base = MagicMock()
    bad_base.metadata.create_all.side_effect = Exception("DB down")
    monkeypatch.setattr(main_module, "Base", bad_base)

    # Must not raise
    main_module._init_db()


@pytest.mark.asyncio
async def test_lifespan_calls_init_db(monkeypatch) -> None:
    import app.main as main_module

    called: dict = {}
    monkeypatch.setattr(
        main_module,
        "_init_db",
        lambda: called.update({"ok": True}),
    )

    async with main_module.lifespan(main_module.app):
        pass

    assert called.get("ok") is True
