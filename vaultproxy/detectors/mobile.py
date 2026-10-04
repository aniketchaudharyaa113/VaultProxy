import re
from typing import List
from vaultproxy.detectors import Span

# Indian mobile: optional +91 or 0, then [6-9] and 9 digits (allowing one space or hyphen after the 5th digit of the main 10 digits)
MOBILE_REGEX = re.compile(
    r"(?<!\d)(?:\+91[ -]?|0)?[6-9]\d{4}[ -]?\d{5}(?!\d)"
)


def detect_mobile(text: str) -> List[Span]:
    spans: List[Span] = []
    for match in MOBILE_REGEX.finditer(text):
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
