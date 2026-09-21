"""
Real Azure AI Translator adapter (CONFIG-REQUIRED — see
docs/DITSALA_VIP_SPEC.md). Follows Azure's publicly documented Translator
Text API v3.0 contract but has not been exercised against a live Azure
account in this environment — same "adapter unverified against a live
vendor" caveat as Stitch/Smile ID/Deepgram, tracked in
docs/SECURITY_GAPS.md. Credentials never leave the backend (§5, §20) —
this class is only ever constructed here, never referenced from mobile.
"""

import httpx

from app.core.config import Settings
from app.domain.translation.interfaces import TranslationProvider, TranslationResult

_API_VERSION = "3.0"
_TIMEOUT_SECONDS = 15.0
PROVIDER_NAME = "azure"


class AzureTranslationProvider(TranslationProvider):
    def __init__(self, *, endpoint: str, region: str, api_key: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Ocp-Apim-Subscription-Region": region,
            "Content-Type": "application/json",
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> "AzureTranslationProvider":
        return cls(
            endpoint=settings.azure_translator_endpoint,
            region=settings.azure_translator_region,
            api_key=settings.azure_translator_key,
        )

    async def translate(
        self, *, text: str, source_language: str | None, target_language: str
    ) -> TranslationResult:
        params = {"api-version": _API_VERSION, "to": target_language}
        if source_language:
            params["from"] = source_language
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self._endpoint}/translate",
                    params=params,
                    headers=self._headers,
                    json=[{"text": text}],
                )
                response.raise_for_status()
            payload = response.json()
            entry = payload[0]
            translated_text = entry["translations"][0]["text"]
            resolved_source = source_language or entry.get("detectedLanguage", {}).get(
                "language", "und"
            )
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            return TranslationResult(
                original_text=text,
                translated_text="",
                source_language=source_language or "und",
                target_language=target_language,
                provider=PROVIDER_NAME,
                status="failed",
                error_message=str(exc),
            )
        return TranslationResult(
            original_text=text,
            translated_text=translated_text,
            source_language=resolved_source,
            target_language=target_language,
            provider=PROVIDER_NAME,
            status="completed",
        )

    async def detect_language(self, *, text: str) -> str:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self._endpoint}/detect",
                params={"api-version": _API_VERSION},
                headers=self._headers,
                json=[{"text": text}],
            )
            response.raise_for_status()
        payload = response.json()
        return str(payload[0].get("language", "und"))
