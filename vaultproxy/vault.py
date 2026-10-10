from vaultproxy.detectors import Span


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

    def clear(self) -> None:
        self.value_to_token.clear()
        self.token_to_value.clear()
        self.type_counts.clear()
