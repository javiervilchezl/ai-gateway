import json
import logging
import re
from time import perf_counter

import httpx

from app.clients.services import ServiceClient
from app.core.config import settings
from app.core.observability import (
    estimate_cost,
    get_langfuse_client,
    langfuse_trace_end,
    langfuse_trace_start,
)
from app.providers.base import LLMProvider
from app.schemas.analyze import (
    AnalysisMetadata,
    AnalyzeRequest,
    AnalyzeResponse,
)


class OrchestratorService:
    MAX_ROUTING_TEXT_CHARS = 2000
    MAX_DOWNSTREAM_TEXT_CHARS = 12000

    def __init__(
        self,
        service_client: ServiceClient,
        provider: LLMProvider,
    ) -> None:
        self.service_client = service_client
        self.provider = provider
        self.logger = logging.getLogger("gateway.orchestrator")
        self.langfuse_client = get_langfuse_client()

    async def analyze_pdf_bytes(
        self,
        file_name: str,
        payload: bytes,
    ) -> AnalyzeResponse:
        started_at = perf_counter()
        trace = langfuse_trace_start(
            self.langfuse_client,
            name="gateway.analyze_pdf_upload",
            input_data={"file_name": file_name, "provider": settings.provider},
        )
        pdf_result = await self.service_client.analyze_pdf_bytes(
            file_name,
            payload,
        )

        # Extract text for classification and intent detection
        pdf_text = pdf_result.get("text", "")

        # Classify the PDF content with default labels
        classification = await self._safe_classify(
            pdf_text,
            ["support", "sales", "complaint"],
        )
        category = classification.get("label")
        confidence = classification.get("confidence")

        # Detect intent from PDF content
        detected = await self._safe_detect_intent(pdf_text)
        intent = detected.get("intent")
        entities = detected.get("entities", {})

        metadata = AnalysisMetadata(
            provider=settings.provider,
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
            prompt="Delegated to pdf-service + classifier + intent",
            cost_estimate=estimate_cost(
                settings.provider,
                pdf_text[:12000],
                json.dumps({
                    "summary": pdf_result.get("summary", ""),
                    "topics": pdf_result.get("topics", []),
                    "category": category,
                    "intent": intent,
                }),
            ),
        )
        response = AnalyzeResponse(
            input_type="pdf",
            summary=pdf_result.get("summary"),
            topics=pdf_result.get("topics", []),
            category=category,
            confidence=confidence,
            intent=intent,
            entities=entities,
            metadata=metadata,
        )
        langfuse_trace_end(trace, response.model_dump())
        return response

    async def analyze(self, payload: AnalyzeRequest) -> AnalyzeResponse:
        started_at = perf_counter()
        trace = langfuse_trace_start(
            self.langfuse_client,
            name="gateway.analyze",
            input_data=payload.model_dump(),
        )

        if payload.input_type == "pdf":
            if not payload.content:
                raise ValueError("PDF content must be a local file path")
            pdf_result = await self.service_client.analyze_pdf(payload.content)

            # Extract text for classification and intent detection
            pdf_text = pdf_result.get("text", "")

            # Classify the PDF content with provided labels or defaults
            labels = (
                payload.labels
                if payload.labels
                else ["support", "sales", "complaint"]
            )
            classification = await self._safe_classify(
                pdf_text,
                labels,
            )
            category = classification.get("label")
            confidence = classification.get("confidence")

            # Detect intent from PDF content
            detected = await self._safe_detect_intent(pdf_text)
            intent = detected.get("intent")
            entities = detected.get("entities", {})

            metadata = AnalysisMetadata(
                provider=settings.provider,
                latency_ms=round((perf_counter() - started_at) * 1000, 2),
                prompt="Delegated to pdf-service + classifier + intent",
                cost_estimate=estimate_cost(
                    settings.provider,
                    pdf_text[:12000],
                    json.dumps({
                        "summary": pdf_result.get("summary", ""),
                        "topics": pdf_result.get("topics", []),
                        "category": category,
                        "intent": intent,
                    }),
                ),
            )
            response = AnalyzeResponse(
                input_type="pdf",
                summary=pdf_result.get("summary"),
                topics=pdf_result.get("topics", []),
                category=category,
                confidence=confidence,
                intent=intent,
                entities=entities,
                metadata=metadata,
            )
            langfuse_trace_end(trace, response.model_dump())
            return response

        route = payload.mode
        route_prompt = None
        route_raw = ""
        content = payload.content or ""
        if payload.mode == "auto":
            route_prompt = self._build_route_prompt(content)
            route_raw = await self.provider.generate(
                prompt=route_prompt,
                system_prompt=(
                    "You are a routing engine. Respond only with valid JSON."
                ),
            )
            route = json.loads(route_raw).get("route", "both")

        category = None
        confidence = None
        intent = None
        entities = {}

        if route in {"classify", "both"}:
            classification = await self._safe_classify(
                content,
                payload.labels,
            )
            category = classification.get("label")
            confidence = classification.get("confidence")

        if route in {"intent", "both"}:
            detected = await self._safe_detect_intent(content)
            intent = detected.get("intent")
            entities = detected.get("entities", {})

        latency = round((perf_counter() - started_at) * 1000, 2)
        cost = estimate_cost(settings.provider, route_prompt or "", route_raw)
        if route_prompt is not None:
            self.logger.info(
                json.dumps(
                    {
                        "provider": settings.provider,
                        "latency_ms": latency,
                        "cost_estimate": cost,
                        "prompt": route_prompt,
                    }
                )
            )
        response = AnalyzeResponse(
            input_type="text",
            category=category,
            confidence=confidence,
            intent=intent,
            entities=entities,
            metadata=AnalysisMetadata(
                provider=settings.provider,
                latency_ms=latency,
                prompt=route_prompt,
                cost_estimate=cost,
            ),
        )
        langfuse_trace_end(trace, response.model_dump())
        return response

    def _build_route_prompt(self, content: str) -> str:
        compact = re.sub(r"\s+", " ", content).strip()
        if len(compact) > self.MAX_ROUTING_TEXT_CHARS:
            compact = compact[: self.MAX_ROUTING_TEXT_CHARS].rstrip()
            compact += " [truncated]"
        return (
            "You route text analysis requests. Return JSON with key route "
            "and values classify, intent, or both. "
            f"Text: {compact}"
        )

    async def _safe_classify(
        self,
        text: str,
        labels: list[str],
    ) -> dict:
        text = self._truncate_for_downstream(text)
        try:
            return await self.service_client.classify(text, labels)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            self.logger.warning("classification failed: %s", exc)
            return {}

    async def _safe_detect_intent(self, text: str) -> dict:
        text = self._truncate_for_downstream(text)
        try:
            return await self.service_client.detect_intent(text)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            self.logger.warning("intent detection failed: %s", exc)
            return {}

    def _truncate_for_downstream(self, text: str) -> str:
        if len(text) <= self.MAX_DOWNSTREAM_TEXT_CHARS:
            return text
        return text[: self.MAX_DOWNSTREAM_TEXT_CHARS]
