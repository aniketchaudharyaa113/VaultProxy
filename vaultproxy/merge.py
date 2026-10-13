from vaultproxy.detectors import Span


def _priority(s: Span) -> tuple[int, int, float]:
    """Higher tuple = higher priority.

    1. source=='rule' beats 'gemma'
    2. longer span wins
    3. higher confidence score wins
    """
    return (
        1 if s.source == "rule" else 0,
        s.end - s.start,
        s.score,
    )


def merge_spans(spans: list[Span]) -> list[Span]:
    """Merge overlapping spans, keeping the highest-priority span in each
    overlapping group.

    Priority (descending): source=='rule' > longer span > higher score.

    Algorithm: sort all spans by priority descending, then process greedily.
    A span is kept only if it does not overlap any already-kept span.
    Because higher-priority spans are processed first and never removed,
    every discarded span is guaranteed to be overlapped by a kept span that
    has priority >= the discarded span's priority.

    Guarantees:
    - Output spans never overlap each other.
    - A span is only absent from the output if some kept span overlaps it.
    """
    if not spans:
        return []

    # Sort by priority descending (highest-priority first)
    candidates = sorted(spans, key=_priority, reverse=True)

    result: list[Span] = []
    for curr in candidates:
        # Keep curr only if it doesn't overlap any span already in the result
        overlaps_any = any(
            curr.start < r.end and curr.end > r.start
            for r in result
        )
        if not overlaps_any:
            result.append(curr)
        # else: discard curr — it's covered by a higher-priority kept span

    return sorted(result, key=lambda s: s.start)
