import re

from vaultproxy.detectors import Span
from vaultproxy.detectors.verhoeff import validate_verhoeff

# Aadhaar: 12 digits, first digit 2-9, optional single space or hyphen after every 4 digits
AADHAAR_REGEX = re.compile(r"\b[2-9]\d{3}[\s-]-------------?\d{4}[\s-]?\d{4}\b".replace("-------------", ""))
# Cleaner regex:
AADHAAR_REGEX = re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b")


def detect_aadhaar(text: str) -> list[Span]:
    spans: list[Span] = []
    for match in AADHAAR_REGEX.finditer(text):
        raw_match = match.group(0)
        digits_only = re.sub(r"\D", "", raw_match)
        if len(digits_only) == 12 and validate_verhoeff(digits_only):
            spans.append(
                Span(
                    start=match.start(),
                    end=match.end(),
                    type="AADHAAR",
                    source="rule",
                    score=1.0,
                )
            )
    return spans
