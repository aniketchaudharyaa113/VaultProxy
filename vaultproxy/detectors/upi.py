import re
from typing import List
from vaultproxy.detectors import Span

UPI_HANDLES = (
    r"okaxis|oksbi|okhdfcbank|okicici|ybl|paytm|ibl|axl"
)
UPI_REGEX = re.compile(
    rf"\b[a-zA-Z0-9._-]+@({UPI_HANDLES})\b",
    re.IGNORECASE,
)


def detect_upi(text: str) -> List[Span]:
    spans: List[Span] = []
    for match in UPI_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(),
                end=match.end(),
                type="UPI_ID",
                source="rule",
                score=1.0,
            )
        )
    return spans
