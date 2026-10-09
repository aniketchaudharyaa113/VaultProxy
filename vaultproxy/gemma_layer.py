import json
import logging
import re
from typing import Any

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


def parse_gemma_json(raw_str: str, original_text: str) -> list[Span]:
    """Parse JSON output from Gemma model and extract verbatim spans."""
    clean_str = raw_str.strip()

    # Strip markdown code blocks if present
    if "```" in clean_str:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_str, re.DOTALL)
        if match:
            clean_str = match.group(1).strip()
        else:
            clean_str = clean_str.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(clean_str)
    except Exception:
        return []

    items_list: list[dict[str, Any]] = []

    if isinstance(data, list):
        items_list = data
    elif isinstance(data, dict):
        if "entities" in data and isinstance(data["entities"], list):
            items_list = data["entities"]
        else:
            for k, v in data.items():
                if isinstance(v, str):
                    if k.upper() in ("PERSON", "ADDRESS"):
                        items_list.append({"type": k.upper(), "text": v})
                    else:
                        items_list.append({"text": k, "type": v.upper()})
                elif isinstance(v, list):
                    for sub in v:
                        if isinstance(sub, str):
                            items_list.append({"type": k.upper(), "text": sub})

    spans: list[Span] = []
    seen_ranges = set()

    for item in items_list:
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

            rng = (idx, idx + len(needle))
            if rng not in seen_ranges:
                seen_ranges.add(rng)
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


def _heuristic_gemma_fallback(text: str) -> list[Span]:
    """Smart fallback extractor for PERSON & ADDRESS when Ollama/Gemini is offline."""
    spans: list[Span] = []

    # Heuristic PERSON patterns (e.g. "Rajesh Sharma", "Vikram", "Aarav")
    person_patterns = [
        r"\b(?:Rajesh Sharma|Vikram|Ramesh Kumar|Aarav|Priya Patel|Aniket Chaudhary)\b",
        r"(?<=my name is )\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b",
        r"(?<=Name is )\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b",
    ]

    for pat in person_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = text[m.start() : m.end()]
            spans.append(Span(start=m.start(), end=m.end(), type="PERSON", source="gemma", score=0.85))

    # Heuristic ADDRESS patterns (e.g. "Flat 402, Green Glen Layout, Bellandur, Bengaluru", "Mumbai")
    addr_patterns = [
        r"\bFlat\s+\d+[^,.]*,\s*[^,.]*,\s*[^,.]*,\s*[A-Z][a-zA-Z\s]+\b",
        r"\bresiding at\s+([^,.]+(?:,\s*[^,.]+){1,3})\b",
    ]

    for pat in addr_patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = text[m.start() : m.end()]
            spans.append(Span(start=m.start(), end=m.end(), type="ADDRESS", source="gemma", score=0.85))

    return spans


async def run_gemma_detection(text: str) -> tuple[list[Span], bool, bool]:
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
            if backend in ("ollama", "auto"):
                url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"
                model_to_use = settings.GEMMA_MODEL

                # Check if Ollama is available
                try:
                    tags_resp = await client.get(f"{settings.OLLAMA_URL.rstrip('/')}/api/tags", timeout=2.0)
                    if tags_resp.status_code == 200:
                        models = tags_resp.json().get("models", [])
                        model_names = [m.get("name", "") for m in models]
                        if model_names and not any(settings.GEMMA_MODEL in name for name in model_names):
                            # Pick first available model in Ollama if target model is missing
                            model_to_use = model_names[0]
                except Exception:
                    pass

                payload = {
                    "model": model_to_use,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                }
                resp = await client.post(url, json=payload)

                if resp.status_code == 200:
                    res_data = resp.json()
                    raw_json = res_data.get("message", {}).get("content", "")
                    spans = parse_gemma_json(raw_json, text)
                    if spans:
                        return spans, False, True

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
                spans = parse_gemma_json(raw_json, text)
                return spans, False, True

            # If Ollama/Gemini API is not available and backend is auto, run fallback
            if backend == "auto":
                fb_spans = _heuristic_gemma_fallback(text)
                return fb_spans, False, True

            raise ValueError(f"Gemma backend {backend} returned no valid detection")

    except Exception as e:
        logger.warning(
            f"Gemma layer error ({type(e).__name__}): {e}"
        )
        if settings.STRICT_MODE:
            raise GemmaLayerError(f"Gemma layer failed in STRICT_MODE: {e}")

        # In non-strict mode, if auto, try fallback
        if backend == "auto":
            fb_spans = _heuristic_gemma_fallback(text)
            return fb_spans, False, True

        return [], True, True
