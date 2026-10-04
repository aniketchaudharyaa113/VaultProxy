from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: str
    source: str = "rule"
    score: float = 1.0
