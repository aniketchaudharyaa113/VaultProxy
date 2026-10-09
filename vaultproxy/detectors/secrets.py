import re

from vaultproxy.detectors import Span

AKIA_REGEX = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
GHP_REGEX = re.compile(r"\bghp_[a-zA-Z0-9]{36}\b")
GITHUB_PAT_REGEX = re.compile(r"\bgithub_pat_[a-zA-Z0-9_]+\b")
JWT_REGEX = re.compile(
    r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"
)


def detect_secrets(text: str) -> list[Span]:
    spans: list[Span] = []

    for regex in (AKIA_REGEX, GHP_REGEX, GITHUB_PAT_REGEX, JWT_REGEX):
        for match in regex.finditer(text):
            spans.append(
                Span(
                    start=match.start(),
                    end=match.end(),
                    type="SECRET",
                    source="rule",
                    score=1.0,
                )
            )
    return spans
