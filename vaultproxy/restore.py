import json
import re
from collections.abc import Callable

from vaultproxy.vault import RequestVault


def restore_text(text: str, vault: RequestVault) -> str:
    """Restore tokens in text using vault (case-insensitive token matching)."""
    if not text or not vault.token_to_value:
        return text

    res = text
    sorted_tokens = sorted(
        vault.token_to_value.keys(), key=len, reverse=True
    )
    for token in sorted_tokens:
        val = vault.token_to_value[token]
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        res = pattern.sub(lambda _: val, res)
    return res



def restore_json_text(text: str, vault: RequestVault) -> str:
    """Restore tokens inside a JSON string value, properly JSON-escaping restored values."""
    if not text or not vault.token_to_value:
        return text

    res = text
    sorted_tokens = sorted(
        vault.token_to_value.keys(), key=len, reverse=True
    )
    for token in sorted_tokens:
        val = vault.token_to_value[token]
        escaped_val = json.dumps(val)[1:-1]
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        res = pattern.sub(lambda _: escaped_val, res)
    return res



class StreamRestorer:
    """Buffers streaming token output to restore tokens split across SSE chunks."""

    def __init__(
        self,
        vault: RequestVault,
        json_escape: bool = False,
        trace: Callable[[str, str, str], None] | None = None,
    ):
        self.vault = vault
        self.json_escape = json_escape
        self.buffer = ""
        self.trace = trace

    def _restore(self, text: str) -> str:
        if self.json_escape:
            return restore_json_text(text, self.vault)
        return restore_text(text, self.vault)

    def feed(self, text: str) -> str:
        self.buffer += text
        last_bracket = self.buffer.rfind("[")
        if last_bracket != -1:
            closing_bracket = self.buffer.find("]", last_bracket)
            if closing_bracket == -1:
                held_len = len(self.buffer) - last_bracket
                if held_len <= 24:
                    to_process = self.buffer[:last_bracket]
                    self.buffer = self.buffer[last_bracket:]
                    emitted = self._restore(to_process)
                    if self.trace:
                        self.trace(text, self.buffer, emitted)
                    return emitted

        to_process = self.buffer
        self.buffer = ""
        emitted = self._restore(to_process)
        if self.trace:
            self.trace(text, self.buffer, emitted)
        return emitted

    def flush(self) -> str:
        to_process = self.buffer
        self.buffer = ""
        emitted = self._restore(to_process)
        if self.trace:
            self.trace("", self.buffer, emitted)
        return emitted

