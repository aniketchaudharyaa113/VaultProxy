import re
from vaultproxy.vault import RequestVault


def restore_text(text: str, vault: RequestVault) -> str:
    """Restore tokens in text using vault (case-insensitive token matching)."""
    if not text or not vault.token_to_value:
        return text

    res = text
    # Order tokens by length descending to avoid partial token replacement issues
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

    def __init__(self, vault: RequestVault):
        self.vault = vault
        self.buffer = ""

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
                    return restore_text(to_process, self.vault)

        to_process = self.buffer
        self.buffer = ""
        return restore_text(to_process, self.vault)

    def flush(self) -> str:
        to_process = self.buffer
        self.buffer = ""
        return restore_text(to_process, self.vault)
