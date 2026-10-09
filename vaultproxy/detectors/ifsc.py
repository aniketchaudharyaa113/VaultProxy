import re

from vaultproxy.detectors import Span

IFSC_REGEX = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")


def detect_ifsc(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in IFSC_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(),
                end=match.end(),
                type="IFSC",
                source="rule",
                score=1.0,
            )
        )
    return spans
