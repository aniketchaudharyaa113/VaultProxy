import asyncio
import json
import logging
import re
import time
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


class GemmaResponseSchema(BaseModel):
    entities: list[GemmaEntity]


GEMMA_PROMPT_TEMPLATE = """Extract all PERSON names and ADDRESS entities from the input text below.
You MUST output JSON ONLY as a JSON object matching schema: {{"entities": [{{"text": "...", "type": "PERSON"|"ADDRESS"}}]}}.
Each object must have "text" (exact verbatim substring from input text) and "type" ("PERSON" or "ADDRESS").

Input text: {text}
"""


class CircuitBreaker:
    """Circuit breaker for SLM layer calls."""

    def __init__(
        self, failure_threshold: int = 3, cooldown_seconds: float = 30.0
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.failure_count = 0
        self.cooldown_until = 0.0

    def allow_request(self) -> bool:
        now = time.monotonic()
        if self.state == "OPEN":
            if now >= self.cooldown_until:
                self.state = "HALF_OPEN"
                return True
            return False
        return True

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold or self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.cooldown_until = time.monotonic() + self.cooldown_seconds


circuit_breaker = CircuitBreaker(
    failure_threshold=settings.GEMMA_CIRCUIT_BREAKER_FAILURES,
    cooldown_seconds=settings.GEMMA_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
)

_semaphore_instance: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore_instance, _semaphore_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _semaphore_instance is None or _semaphore_loop != loop:
        _semaphore_instance = asyncio.Semaphore(settings.GEMMA_CONCURRENCY_LIMIT)
        _semaphore_loop = loop
    return _semaphore_instance


def reset_semaphore() -> None:
    global _semaphore_instance, _semaphore_loop
    _semaphore_instance = None
    _semaphore_loop = None


LAST_SLM_MODEL_NAME: str = ""
LAST_SLM_LATENCY_MS: float = 0.0

_last_probe_time: float = 0.0
_last_probe_ok: bool = False
_last_probe_model: str | None = None


async def check_slm_readiness() -> tuple[bool, str | None]:
    """Probe the SLM backend and model presence, cached at most 10 seconds.

    Returns:
        (is_ready, verified_model_name)
    """
    global _last_probe_time, _last_probe_ok, _last_probe_model, LAST_SLM_MODEL_NAME

    backend = settings.GEMMA_BACKEND.lower()
    if backend == "off":
        return True, "off"

    if circuit_breaker.state == "OPEN":
        return False, None

    now = time.monotonic()
    if _last_probe_time > 0 and (now - _last_probe_time) < 10.0:
        return _last_probe_ok, _last_probe_model

    _last_probe_time = now

    if backend == "ollama":
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{settings.OLLAMA_URL.rstrip('/')}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    model_present = any(
                        settings.GEMMA_MODEL in name for name in model_names
                    )
                    if model_present:
                        _last_probe_ok = True
                        _last_probe_model = settings.GEMMA_MODEL
                        LAST_SLM_MODEL_NAME = settings.GEMMA_MODEL
                        return True, _last_probe_model
                    elif settings.GEMMA_AUTODISCOVER and model_names:
                        _last_probe_ok = True
                        _last_probe_model = model_names[0]
                        LAST_SLM_MODEL_NAME = model_names[0]
                        return True, _last_probe_model
        except Exception:
            pass
        _last_probe_ok = False
        _last_probe_model = None
        return False, None

    elif backend == "gemini":
        if not settings.GEMINI_API_KEY:
            _last_probe_ok = False
            _last_probe_model = None
            return False, None
        _last_probe_ok = True
        _last_probe_model = settings.GEMMA_MODEL
        LAST_SLM_MODEL_NAME = settings.GEMMA_MODEL
        return True, _last_probe_model

    _last_probe_ok = False
    _last_probe_model = None
    return False, None


def get_source_label(model_name: str) -> str:
    """Return 'gemma' if model starts with 'gemma', otherwise 'slm:<model_name>'."""
    if model_name.lower().startswith("gemma"):
        return "gemma"
    return f"slm:{model_name}"


def parse_gemma_json(
    raw_str: str, original_text: str, source_label: str = "gemma"
) -> tuple[list[Span], bool]:
    """Parse JSON output from Gemma/SLM model and extract verbatim spans.

    Returns:
        (spans, is_valid_parse)
    """
    clean_str = raw_str.strip()

    if "```" in clean_str:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean_str, re.DOTALL)
        if match:
            clean_str = match.group(1).strip()
        else:
            clean_str = clean_str.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(clean_str)
    except Exception:
        return [], False

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
                        source=source_label,
                        score=0.9,
                    )
                )
            start_idx = idx + len(needle)

    return spans, True


async def run_gemma_detection(text: str) -> tuple[list[Span], bool, bool]:
    """Run Gemma model detection on text with queue timeout, circuit breaker and concurrency controls.

    Returns:
        (spans, degraded, gemma_used)
    """
    global LAST_SLM_MODEL_NAME, LAST_SLM_LATENCY_MS

    backend = settings.GEMMA_BACKEND.lower()
    if backend == "off":
        return [], False, False

    if not circuit_breaker.allow_request():
        logger.warning("Circuit breaker is OPEN.")
        if settings.STRICT_MODE:
            raise GemmaLayerError(
                "VaultProxy fail-closed: Gemma layer circuit breaker is OPEN."
            )
        return [], True, False

    sem = get_semaphore()
    sem_acquired = False

    # Queue timeout: GEMMA_TIMEOUT_SECONDS does NOT include time spent waiting in concurrency queue
    try:
        await asyncio.wait_for(
            sem.acquire(), timeout=settings.GEMMA_QUEUE_TIMEOUT_SECONDS
        )
        sem_acquired = True
    except (asyncio.TimeoutError, TimeoutError) as te:
        logger.warning("Gemma concurrency queue timeout exceeded.")
        circuit_breaker.record_failure()
        if settings.STRICT_MODE:
            raise GemmaLayerError(
                "VaultProxy fail-closed: Gemma queue timeout waiting for concurrency slot."
            ) from te
        return [], True, False

    prompt = GEMMA_PROMPT_TEMPLATE.format(text=text)
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=settings.GEMMA_TIMEOUT_SECONDS) as client:
            if backend == "ollama":
                url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"
                model_to_use = settings.GEMMA_MODEL

                tags_resp = await client.get(
                    f"{settings.OLLAMA_URL.rstrip('/')}/api/tags",
                    timeout=2.0,
                )
                if tags_resp.status_code == 200:
                    models = tags_resp.json().get("models", [])
                    model_names = [m.get("name", "") for m in models]

                    # Check if requested model is installed
                    model_present = any(
                        settings.GEMMA_MODEL in name for name in model_names
                    )
                    if not model_present:
                        if settings.GEMMA_AUTODISCOVER and model_names:
                            model_to_use = model_names[0]
                        else:
                            raise ValueError(
                                f"Configured model '{settings.GEMMA_MODEL}' is not installed in Ollama."
                            )

                payload: dict[str, Any] = {
                    "model": model_to_use,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": GemmaResponseSchema.model_json_schema(),
                    "options": {
                        "temperature": settings.GEMMA_TEMPERATURE,
                        "num_predict": settings.GEMMA_MAX_TOKENS,
                    },
                    "keep_alive": settings.GEMMA_KEEP_ALIVE,
                }
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    raise ValueError(f"Ollama returned HTTP status {resp.status_code}")

                res_data = resp.json()
                raw_json = res_data.get("message", {}).get("content", "")

                src_label = get_source_label(model_to_use)
                spans, valid_parse = parse_gemma_json(
                    raw_json, text, source_label=src_label
                )

                if not valid_parse:
                    raise ValueError("Unparseable or schema-violating JSON from SLM.")

                LAST_SLM_MODEL_NAME = model_to_use
                LAST_SLM_LATENCY_MS = (time.perf_counter() - t0) * 1000
                circuit_breaker.record_success()
                return spans, False, True

            elif backend == "gemini":
                model_to_use = settings.GEMMA_MODEL
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_use}:generateContent"
                headers = {"x-goog-api-key": settings.GEMINI_API_KEY}
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": settings.GEMMA_TEMPERATURE,
                        "maxOutputTokens": settings.GEMMA_MAX_TOKENS,
                        "responseMimeType": "application/json",
                    },
                }
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                res_data = resp.json()
                raw_json = (
                    res_data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                src_label = get_source_label(model_to_use)
                spans, valid_parse = parse_gemma_json(
                    raw_json, text, source_label=src_label
                )

                if not valid_parse:
                    raise ValueError(
                        "Unparseable or schema-violating JSON from Gemini SLM."
                    )

                LAST_SLM_MODEL_NAME = model_to_use
                LAST_SLM_LATENCY_MS = (time.perf_counter() - t0) * 1000
                circuit_breaker.record_success()
                return spans, False, True

            raise ValueError(f"Unsupported backend {backend}")

    except Exception as e:
        err_msg = str(e)
        if "http" in err_msg.lower() or "://" in err_msg or "key=" in err_msg.lower():
            err_msg = f"{type(e).__name__} (details redacted)"
        logger.warning(f"Gemma layer error ({type(e).__name__}): {err_msg}")
        circuit_breaker.record_failure()

        if settings.STRICT_MODE:
            raise GemmaLayerError(f"Gemma layer failed in STRICT_MODE: {err_msg}") from e



        return [], True, False
    finally:
        if sem_acquired:
            sem.release()


async def startup_self_test() -> tuple[bool, str, float]:
    """Startup self-test that checks config, verifies model presence, makes one tiny call, and records exact model name & latency.

    If configured model is missing (and GEMMA_AUTODISCOVER=False), logs warning and returns (False, GEMMA_MODEL, 0.0).
    """
    if settings.GEMMA_BACKEND.lower() == "off":
        return True, "off", 0.0

    try:
        spans, degraded, gemma_used = await run_gemma_detection("test warmup")
        return (
            not degraded,
            LAST_SLM_MODEL_NAME or settings.GEMMA_MODEL,
            LAST_SLM_LATENCY_MS,
        )
    except Exception as e:
        logger.warning(
            f"Startup self-test failed for model '{settings.GEMMA_MODEL}': {e}"
        )
        return False, settings.GEMMA_MODEL, 0.0
