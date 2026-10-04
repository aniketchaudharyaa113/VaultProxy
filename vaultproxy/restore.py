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
        # Case insensitive replacement
        import re

        pattern = re.compile(re.escape(token), re.IGNORECASE)
        res = pattern.sub(val, res)
    return res
