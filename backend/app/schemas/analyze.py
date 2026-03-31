from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    input_type: Literal["text", "pdf"]
    content: str | None = None
    labels: list[str] = Field(
        default_factory=lambda: ["support", "sales", "complaint"]
    )
    mode: Literal["auto", "classify", "intent", "both"] = "auto"


class AnalysisMetadata(BaseModel):
    provider: str
    latency_ms: float
    prompt: str | None = None
    cost_estimate: float


class AnalyzeResponse(BaseModel):
    input_type: str
    summary: str | None = None
    topics: list[str] = Field(default_factory=list)
    category: str | None = None
    confidence: float | None = None
    intent: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    metadata: AnalysisMetadata
