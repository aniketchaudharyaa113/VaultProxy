import json
import logging
import re
from typing import List, Tuple
import httpx
from pydantic import BaseModel, ValidationError
from vaultproxy.config import settings
from vaultproxy.detectors import Span

logger = logging.getLogger("vaultproxy.gemma_layer")


class GemmaLayerError(Exception):
    """Raised when Gemma layer fails in STRICT_MODE."""

    pass


class GemmaEntity(BaseModel):
    text: str
    type: str


GEMMA_PROMPT_TEMPLATE = """Extract all PERSON names and ADDRESS entities from the input text below.
You MUST output JSON ONLY as a JSON array of objects.
Do not include any text, code block fences, or explanations outside the JSON array.
Each object must have "text" (exact verbatim substring from input text) and "type" ("PERSON" or "ADDRESS").

Input text: {text}
"""


def parse_gemma_json(raw_str: str, original_text: str) -> List[Span]:
    """Parse JSON output from Gemma model and extract verbatim spans."""
    clean_str = raw_str.strip()

    # Strip markdown code blocks if present
    if "```" in clean_str:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_str, re.DOTALL)
        if match:
            clean_str = match.group(1).strip()
        else:
            clean_str = clean_str.replace("```json", "").replace("```", "").strip()

    data = json.loads(clean_str)
    if not isinstance(data, list):
        return []

    spans: List[Span] = []
    for item in data:
        try:
            entity = GemmaEntity(**item)
        except (ValidationError, TypeError, ValueError):
            continue

        ent_type = entity.type.upper()
        if ent_type not in ("PERSON", "ADDRESS"):
            continue

        needle = entity.text.strip()
        if not needle:
            continue

        # Find all verbatim occurrences in original_text
        start_idx = 0
        while True:
            idx = original_text.find(needle, start_idx)
            if idx == -1:
                break
            spans.append(
                Span(
                    start=idx,
                    end=idx + len(needle),
                    type=ent_type,
                    source="gemma",
                    score=0.9,
                )
            )
            start_idx = idx + len(needle)

    return spans


async def run_gemma_detection(text: str) -> Tuple[List[Span], bool, bool]:
    """Run Gemma model detection on text.

    Returns:
        (spans, degraded, gemma_used)
    """
    backend = settings.GEMMA_BACKEND.lower()
    if backend == "off":
        return [], False, False

    prompt = GEMMA_PROMPT_TEMPLATE.format(text=text)

    try:
        async with httpx.AsyncClient(
            timeout=settings.GEMMA_TIMEOUT_SECONDS
        ) as client:
            if backend == "ollama":
                url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"
                payload = {
                    "model": settings.GEMMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                }
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                res_data = resp.json()
                raw_json = res_data.get("message", {}).get("content", "")

            elif backend == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMMA_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}]
                }
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                res_data = resp.json()
                raw_json = (
                    res_data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
            else:
                raise ValueError(f"Unknown GEMMA_BACKEND: {backend}")

            spans = parse_gemma_json(raw_json, text)
            return spans, False, True

    except Exception as e:
        logger.warning(
            f"Gemma layer error ({type(e).__name__}): {e}"
        )
        if settings.STRICT_MODE:
            raise GemmaLayerError(f"Gemma layer failed in STRICT_MODE: {e}")
        return [], True, True
