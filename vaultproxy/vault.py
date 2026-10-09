from typing import Any

from vaultproxy.detectors import Span
from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.gemma_layer import run_gemma_detection
from vaultproxy.merge import merge_spans


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
                rule_spans = run_rule_detectors(content)
                gemma_spans, degraded, gemma_used = await run_gemma_detection(
                    content
                )
                if degraded:
                    any_degraded = True
                if gemma_used:
                    any_gemma_used = True

                all_spans = merge_spans(rule_spans + gemma_spans)
                new_msg["content"] = self.mask_text(content, all_spans)
            elif isinstance(content, list):
                masked_list = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        txt = item.get("text", "")
                        rule_spans = run_rule_detectors(txt)
                        gemma_spans, degraded, gemma_used = (
                            await run_gemma_detection(txt)
                        )
                        if degraded:
                            any_degraded = True
                        if gemma_used:
                            any_gemma_used = True

                        all_spans = merge_spans(rule_spans + gemma_spans)
                        item_copy = dict(item)
                        item_copy["text"] = self.mask_text(txt, all_spans)
                        masked_list.append(item_copy)
                    else:
                        masked_list.append(item)
                new_msg["content"] = masked_list
            masked_msgs.append(new_msg)

        return masked_msgs, any_degraded, any_gemma_used
