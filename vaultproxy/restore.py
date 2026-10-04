import re
from typing import Callable, Optional
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
        res = pattern.sub(val, res)
    return res


class StreamRestorer:
    """Buffers streaming token output to restore tokens split across SSE chunks."""

    def __init__(
        self,
        vault: RequestVault,
        trace: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.vault = vault
        self.buffer = ""
        self.trace = trace

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
                    emitted = restore_text(to_process, self.vault)
                    if self.trace:
                        self.trace(text, self.buffer, emitted)
                    return emitted

        to_process = self.buffer
        self.buffer = ""
        emitted = restore_text(to_process, self.vault)
        if self.trace:
            self.trace(text, self.buffer, emitted)
        return emitted

    def flush(self) -> str:
        to_process = self.buffer
        self.buffer = ""
        emitted = restore_text(to_process, self.vault)
        if self.trace:
            self.trace("", self.buffer, emitted)
        return emitted
