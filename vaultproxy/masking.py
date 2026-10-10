import json
import re
import time
from typing import Any

from vaultproxy.config import settings
from vaultproxy.detectors import Span
from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.gemma_layer import GemmaLayerError, run_gemma_detection
from vaultproxy.merge import merge_spans
from vaultproxy.vault import RequestVault

SLM_CHUNK_CHARS = 6000
SLM_OVERLAP_CHARS = 300
SLM_MAX_CHUNKS = 4

HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{16,}$")
BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/=]{32,}$")


def is_candidate_for_slm(text: str) -> bool:
    """Check if a string qualifies for SLM inspection (length >= 4, has letters, not hex/base64)."""
    if not isinstance(text, str) or len(text) < 4:
        return False
    if not any(c.isalpha() for c in text):
        return False
    if HEX_PATTERN.match(text) or BASE64_PATTERN.match(text):
        return False
    return True


def has_non_text_parts(obj: Any) -> bool:
    """Check if payload contains non-text content (image_url, input_audio, file)."""
    if isinstance(obj, dict):
        if any(k in obj for k in ("image_url", "input_audio", "file")):
            return True
        if obj.get("type") in ("image_url", "input_audio", "file"):
            return True
        return any(has_non_text_parts(v) for v in obj.values())
    elif isinstance(obj, list):
        return any(has_non_text_parts(item) for item in obj)
    return False


def is_exact_structural_allowlist_position(k: str, path: list[Any]) -> bool:
    """Check if (k, path) matches an exact structural allowlist position that must be skipped from masking.

    Allowed positions to skip:
    1. Top-level payload["model"]
    2. Message role: messages[i]["role"]
    3. Multimodal content part type: messages[i]["content"][j]["type"]
    """
    if len(path) == 0 and k == "model":
        return True
    if len(path) == 2 and path[0] == "messages" and k == "role":
        return True
    if (
        len(path) == 4
        and path[0] == "messages"
        and path[2] == "content"
        and k == "type"
    ):
        return True
    return False


def chunk_combined_text(
    text: str,
    max_chunk_size: int = SLM_CHUNK_CHARS,
    overlap_chars: int = SLM_OVERLAP_CHARS,
) -> list[tuple[int, int, str]]:
    """Split text into overlapping chunks of size <= max_chunk_size with overlap_chars overlap."""
    chunks: list[tuple[int, int, str]] = []
    start = 0
    n = len(text)
    min_progress = max(1, overlap_chars + 1)
    while start < n:
        if start + max_chunk_size >= n:
            chunks.append((start, n, text[start:n]))
            break
        target_end = start + max_chunk_size
        best = -1
        min_sep_pos = start + min_progress
        for sep in ("\n---\n", "\n\n", "\n", ". ", "? ", "! ", " "):
            idx = text.rfind(sep, min_sep_pos, target_end)
            if idx >= min_sep_pos:
                best = idx + len(sep) if sep in (". ", "? ", "! ") else idx
                break
        if best < min_sep_pos:
            best = target_end
        chunks.append((start, best, text[start:best]))
        next_start = max(start + 1, best - overlap_chars)
        if next_start >= n:
            break
        start = next_start
    return chunks


class MaskingEngine:
    """Handles request payload masking, structural allowlisting, and SLM chunking."""

    def __init__(self, vault: RequestVault) -> None:
        self.vault = vault

    async def mask_payload(
        self, body_json: dict[str, Any]
    ) -> tuple[dict[str, Any], bool, bool, int]:
        """Deep-walk request payload, scanning every string value except structural allowlist positions."""
        collected_strings: list[tuple[str, list[Any]]] = []

        def _collect(obj: Any, path: list[Any]) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if is_exact_structural_allowlist_position(k, path) and isinstance(
                        v, str
                    ):
                        continue
                    if k == "arguments" and isinstance(v, str):
                        try:
                            parsed_args = json.loads(v)
                            if isinstance(parsed_args, (dict, list)):
                                _collect(parsed_args, path + [k])
                                continue
                        except Exception:
                            pass
                    _collect(v, path + [k])
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    _collect(item, path + [idx])
            elif isinstance(obj, str):
                collected_strings.append((obj, path))

        _collect(body_json, [])

        slm_candidates: list[tuple[int, str]] = []
        for idx, (str_val, _) in enumerate(collected_strings):
            if is_candidate_for_slm(str_val):
                slm_candidates.append((idx, str_val))

        slm_spans_per_string: dict[int, list[Span]] = {
            i: [] for i in range(len(collected_strings))
        }
        any_degraded = False
        any_gemma_used = False
        slm_chunks_count = 0

        if slm_candidates:
            combined_text_parts = [s for _, s in slm_candidates]
            combined_text = "\n---\n".join(combined_text_parts)

            chunks = chunk_combined_text(
                combined_text,
                max_chunk_size=SLM_CHUNK_CHARS,
                overlap_chars=SLM_OVERLAP_CHARS,
            )
            slm_chunks_count = len(chunks)
            time_budget = settings.GEMMA_TIMEOUT_SECONDS * 2.0

            if len(chunks) > SLM_MAX_CHUNKS:
                if settings.STRICT_MODE:
                    raise GemmaLayerError(
                        f"Payload text length requiring {len(chunks)} chunks exceeds maximum allowed chunks ({SLM_MAX_CHUNKS}) in STRICT_MODE."
                    )
                else:
                    any_degraded = True
            else:
                start_time = time.monotonic()
                offsets = []
                curr_pos = 0
                for original_idx, text in slm_candidates:
                    start_pos = curr_pos
                    end_pos = curr_pos + len(text)
                    offsets.append((start_pos, end_pos, original_idx, text))
                    curr_pos = end_pos + 5

                for chunk_start, chunk_end, chunk_str in chunks:
                    if time.monotonic() - start_time > time_budget:
                        if settings.STRICT_MODE:
                            raise GemmaLayerError(
                                "SLM chunking inspection exceeded total time budget in STRICT_MODE."
                            )
                        else:
                            any_degraded = True
                            break

                    gemma_spans, deg, gem = await run_gemma_detection(chunk_str)
                    any_degraded = any_degraded or deg
                    any_gemma_used = any_gemma_used or gem

                    for span in gemma_spans:
                        adj_start = span.start + chunk_start
                        adj_end = span.end + chunk_start
                        for start_pos, end_pos, orig_idx, text in offsets:
                            if adj_start >= start_pos and adj_end <= end_pos:
                                rel_start = adj_start - start_pos
                                rel_end = adj_end - start_pos
                                slm_spans_per_string[orig_idx].append(
                                    Span(
                                        start=rel_start,
                                        end=rel_end,
                                        type=span.type,
                                        score=span.score,
                                        source=span.source,
                                    )
                                )
                                break

        masked_string_map: dict[int, str] = {}
        for idx, (str_val, _) in enumerate(collected_strings):
            rule_spans = run_rule_detectors(str_val)
            gemma_spans = slm_spans_per_string[idx]
            all_spans = merge_spans(rule_spans + gemma_spans)
            masked_string_map[idx] = self.vault.mask_text(str_val, all_spans)

        str_counter = 0

        def _reconstruct(obj: Any, path: list[Any]) -> Any:
            nonlocal str_counter
            if isinstance(obj, dict):
                res: dict[str, Any] = {}
                for k, v in obj.items():
                    if len(path) == 0 and k == "messages" and isinstance(v, list):
                        system_msg = {
                            "role": "system",
                            "content": "IMPORTANT: Keep all token placeholders formatted like [TYPE_N] (e.g. [PAN_1], [AADHAAR_1]) EXACTLY as they are in your response. Do not modify, translate, or remove them.",
                        }
                        reconstructed_messages = [system_msg]
                        for idx, m in enumerate(v):
                            reconstructed_messages.append(
                                _reconstruct(m, path + [k, idx])
                            )
                        res[k] = reconstructed_messages
                    elif is_exact_structural_allowlist_position(k, path) and isinstance(
                        v, str
                    ):
                        res[k] = v
                    elif k == "arguments" and isinstance(v, str):
                        try:
                            parsed_args = json.loads(v)
                            if isinstance(parsed_args, (dict, list)):
                                reconstructed_args = _reconstruct(
                                    parsed_args, path + [k]
                                )
                                res[k] = json.dumps(reconstructed_args)
                                continue
                        except Exception:
                            pass
                        res[k] = masked_string_map[str_counter]
                        str_counter += 1
                    else:
                        res[k] = _reconstruct(v, path + [k])
                return res
            elif isinstance(obj, list):
                return [
                    _reconstruct(item, path + [idx]) for idx, item in enumerate(obj)
                ]
            elif isinstance(obj, str):
                m_val = masked_string_map[str_counter]
                str_counter += 1
                return m_val
            return obj

        masked_payload = _reconstruct(body_json, [])
        return masked_payload, any_degraded, any_gemma_used, slm_chunks_count
