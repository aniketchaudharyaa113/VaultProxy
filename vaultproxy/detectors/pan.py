import re

from vaultproxy.detectors import Span

PAN_REGEX = re.compile(r"\b[A-Z]{3}[PCHFABLJGT][A-Z]\d{4}[A-Z]\b")


def detect_pan(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in PAN_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(),
                end=match.end(),
                type="PAN",
                source="rule",
                score=1.0,
            )
        )
    return spans
