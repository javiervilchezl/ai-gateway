from pathlib import Path

import httpx

from app.core.config import settings


class ServiceClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=60.0)

    def _internal_headers(self) -> dict[str, str]:
        if not settings.internal_service_api_key:
            return {}
        return {
            settings.internal_service_api_key_header: settings.internal_service_api_key
        }

    async def analyze_pdf_bytes(self, file_name: str, payload: bytes) -> dict:
        files = {"file": (file_name, payload, "application/pdf")}
        response = await self.client.post(
            f"{settings.pdf_service_url}/analyze-pdf",
            files=files,
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def analyze_pdf(self, file_path: str) -> dict:
        file_name = Path(file_path).name
        with open(file_path, "rb") as file_handle:
            payload = file_handle.read()
        return await self.analyze_pdf_bytes(file_name, payload)

    async def classify(self, text: str, labels: list[str]) -> dict:
        response = await self.client.post(
            f"{settings.classifier_service_url}/classify",
            json={"text": text, "labels": labels},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def detect_intent(self, text: str) -> dict:
        response = await self.client.post(
            f"{settings.intent_service_url}/detect-intent",
            json={"text": text},
            headers=self._internal_headers(),
        )
        response.raise_for_status()
        return response.json()
