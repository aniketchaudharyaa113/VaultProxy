import re

from vaultproxy.detectors import Span

EMAIL_REGEX = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"
)


def detect_email(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in EMAIL_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(),
                end=match.end(),
                type="EMAIL",
                source="rule",
                score=1.0,
            )
        )
    return spans
