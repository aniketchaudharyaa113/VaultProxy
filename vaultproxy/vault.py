import json
from typing import Any

from vaultproxy.detectors import Span
from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.gemma_layer import run_gemma_detection
from vaultproxy.merge import merge_spans

STRUCTURAL_KEYS = {
    "model",
    "role",
    "type",
    "id",
    "object",
    "finish_reason",
    "index",
    "mode",
    "temperature",
    "top_p",
    "n",
    "stream",
    "presence_penalty",
    "frequency_penalty",
}


def has_non_text_parts(obj: Any) -> bool:
    """Check if a request payload contains non-text media types (image_url, input_audio, file)."""
    if isinstance(obj, dict):
        if any(k in obj for k in ("image_url", "input_audio", "file")):
            return True
        if obj.get("type") in ("image_url", "input_audio", "file"):
            return True
        return any(has_non_text_parts(v) for v in obj.values())
    elif isinstance(obj, list):
        return any(has_non_text_parts(item) for item in obj)
    return False


class RequestVault:
    """Per-request vault mapping raw values to typed tokens (and vice versa)."""

    def __init__(self) -> None:
        self.value_to_token: dict[str, str] = {}
        self.token_to_value: dict[str, str] = {}
        self.type_counts: dict[str, int] = {}

    def get_or_create_token(self, value: str, entity_type: str) -> str:
        if value in self.value_to_token:
            return self.value_to_token[value]

        count = self.type_counts.get(entity_type, 0) + 1
        self.type_counts[entity_type] = count
        token = f"[{entity_type}_{count}]"

        self.value_to_token[value] = token
        self.token_to_value[token] = value
        return token

    def mask_text(self, text: str, spans: list[Span]) -> str:
        if not text or not spans:
            return text

        sorted_spans = sorted(spans, key=lambda s: s.start, reverse=True)
        res = text
        for span in sorted_spans:
            val = text[span.start : span.end]
            token = self.get_or_create_token(val, span.type)
            res = res[: span.start] + token + res[span.end :]
        return res

    async def mask_string(self, text: str) -> tuple[str, bool, bool]:
        if not text:
            return text, False, False
        rule_spans = run_rule_detectors(text)
        gemma_spans, degraded, gemma_used = await run_gemma_detection(text)
        all_spans = merge_spans(rule_spans + gemma_spans)
        masked = self.mask_text(text, all_spans)
        return masked, degraded, gemma_used

    async def mask_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], bool, bool]:
        system_msg = {
            "role": "system",
            "content": "IMPORTANT: Keep all token placeholders formatted like [TYPE_N] (e.g. [PAN_1], [AADHAAR_1]) EXACTLY as they are in your response. Do not modify, translate, or remove them.",
        }

        masked_msgs: list[dict[str, Any]] = [system_msg]
        any_degraded = False
        any_gemma_used = False

        for msg in messages:
            new_msg = dict(msg)
            content = new_msg.get("content")
            if isinstance(content, str):
                masked_content, degraded, gemma_used = await self.mask_string(content)
                if degraded:
                    any_degraded = True
                if gemma_used:
                    any_gemma_used = True
                new_msg["content"] = masked_content
            elif isinstance(content, list):
                masked_list = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        txt = item.get("text", "")
                        masked_txt, degraded, gemma_used = await self.mask_string(txt)
                        if degraded:
                            any_degraded = True
                        if gemma_used:
                            any_gemma_used = True

                        item_copy = dict(item)
                        item_copy["text"] = masked_txt
                        masked_list.append(item_copy)
                    else:
                        masked_list.append(item)
                new_msg["content"] = masked_list
            masked_msgs.append(new_msg)

        return masked_msgs, any_degraded, any_gemma_used

    async def mask_payload(
        self, body_json: dict[str, Any], scope: str = "messages"
    ) -> tuple[dict[str, Any], bool, bool]:
        """Mask a request payload based on the configured scope ('messages' or 'deep')."""
        if scope != "deep":
            res_dict = dict(body_json)
            any_degraded = False
            any_gemma_used = False
            if "messages" in res_dict and isinstance(res_dict["messages"], list):
                msgs, degraded, gemma_used = await self.mask_messages(res_dict["messages"])
                res_dict["messages"] = msgs
                any_degraded = any_degraded or degraded
                any_gemma_used = any_gemma_used or gemma_used
            elif "input" in res_dict:
                inp = res_dict["input"]
                if isinstance(inp, str):
                    m_inp, degraded, gemma_used = await self.mask_string(inp)
                    res_dict["input"] = m_inp
                    any_degraded = any_degraded or degraded
                    any_gemma_used = any_gemma_used or gemma_used
                elif isinstance(inp, list):
                    m_list = []
                    for item in inp:
                        if isinstance(item, str):
                            m_item, degraded, gemma_used = await self.mask_string(item)
                            m_list.append(m_item)
                            any_degraded = any_degraded or degraded
                            any_gemma_used = any_gemma_used or gemma_used
                        else:
                            m_list.append(item)
                    res_dict["input"] = m_list
            return res_dict, any_degraded, any_gemma_used

        # Deep scope: walk payload recursively
        any_degraded = False
        any_gemma_used = False

        async def _walk(obj: Any, parent_key: str = "") -> Any:
            nonlocal any_degraded, any_gemma_used
            if isinstance(obj, dict):
                res = {}
                for k, v in obj.items():
                    if k == "messages" and isinstance(v, list):
                        # Prepend system prompt instruction and walk messages
                        system_msg = {
                            "role": "system",
                            "content": "IMPORTANT: Keep all token placeholders formatted like [TYPE_N] (e.g. [PAN_1], [AADHAAR_1]) EXACTLY as they are in your response. Do not modify, translate, or remove them.",
                        }
                        masked_v = [system_msg]
                        for m in v:
                            masked_m = await _walk(m, k)
                            masked_v.append(masked_m)
                        res[k] = masked_v
                    elif k == "arguments" and isinstance(v, str):
                        try:
                            parsed_args = json.loads(v)
                            masked_args = await _walk(parsed_args, k)
                            res[k] = json.dumps(masked_args)
                        except Exception:
                            m_str, deg, gem = await self.mask_string(v)
                            any_degraded = any_degraded or deg
                            any_gemma_used = any_gemma_used or gem
                            res[k] = m_str
                    else:
                        res[k] = await _walk(v, k)
                return res
            elif isinstance(obj, list):
                res_list = []
                for item in obj:
                    res_list.append(await _walk(item, parent_key))
                return res_list
            elif isinstance(obj, str):
                if parent_key in STRUCTURAL_KEYS:
                    return obj
                m_str, deg, gem = await self.mask_string(obj)
                any_degraded = any_degraded or deg
                any_gemma_used = any_gemma_used or gem
                return m_str
            return obj

        masked_payload = await _walk(body_json)
        return masked_payload, any_degraded, any_gemma_used

