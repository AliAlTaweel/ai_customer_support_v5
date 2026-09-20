"""Thin async wrapper around the google-genai SDK for reply generation and embeddings."""

import asyncio
from google import genai
from google.genai import types
from config import get_settings


class GeminiClient:
    """Wraps genai.Client calls in asyncio.to_thread since the SDK is sync."""

    def __init__(self):
        settings = get_settings()
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._generation_model = settings.GEMINI_GENERATION_MODEL
        self._embedding_model = settings.GEMINI_EMBEDDING_MODEL

    async def embed_text(self, text: str) -> list[float]:
        """Return the embedding vector for a piece of text."""
        response = await asyncio.to_thread(
            self._client.models.embed_content,
            model=self._embedding_model,
            contents=text,
        )
        return response.embeddings[0].values

    async def generate_content(self, system_instruction: str, tools: list[dict], prompt: str):
        """Call Gemini generate_content with function-calling tools; auto-exec disabled
        so the caller inspects the raw function_call instead of the SDK executing it."""
        tool = types.Tool(function_declarations=tools)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[tool],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        return await asyncio.to_thread(
            self._client.models.generate_content,
            model=self._generation_model,
            contents=prompt,
            config=config,
        )
