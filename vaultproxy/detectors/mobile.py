import re

from vaultproxy.detectors import Span

# Indian mobile: optional +91 or 0 prefix, 10 digits starting with [6-9], optional single space or hyphen
MOBILE_REGEX = re.compile(r"(?<!\d)(?:\+91[ -]?|0)?[6-9]\d{3,5}[ -]?\d{4,6}(?!\d)")


def detect_mobile(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in MOBILE_REGEX.finditer(text):
        raw = match.group(0)
        # Extract digits
        digits_only = re.sub(r"\D", "", raw)
        # Strip leading +91 or 0 for length check if present
        if raw.startswith("+91") and len(digits_only) == 12:
            digits_only = digits_only[2:]
        elif raw.startswith("0") and len(digits_only) == 11:
            digits_only = digits_only[1:]

        if len(digits_only) == 10 and digits_only[0] in "6789":
            spans.append(
                Span(
                    start=match.start(),
                    end=match.end(),
                    type="MOBILE",
                    source="rule",
                    score=1.0,
                )
            )
    return spans
