from typing import List
from vaultproxy.detectors import Span


def merge_spans(spans: List[Span]) -> List[Span]:
    """Merge overlapping spans.

    Priority rules:
    1. Rule over Gemma (source == 'rule' over 'gemma')
    2. Longer span length (end - start)
    3. Higher score
    """
    if not spans:
        return []

    # Sort spans by priority
    def sort_key(s: Span):
        source_priority = 1 if s.source == "rule" else 0
        length = s.end - s.start
        return (s.start, -source_priority, -length, -s.score)

    sorted_spans = sorted(spans, key=sort_key)
    result: List[Span] = []

    for curr in sorted_spans:
        overlap = False
        for i, prev in enumerate(result):
            # Check overlap: start < prev.end and end > prev.start
            if curr.start < prev.end and curr.end > prev.start:
                overlap = True
                # Decide which one wins
                prev_rule = 1 if prev.source == "rule" else 0
                curr_rule = 1 if curr.source == "rule" else 0
                prev_len = prev.end - prev.start
                curr_len = curr.end - curr.start

                prev_tuple = (prev_rule, prev_len, prev.score)
                curr_tuple = (curr_rule, curr_len, curr.score)

                if curr_tuple > prev_tuple:
                    result[i] = curr
                break
        if not overlap:
            result.append(curr)

    return sorted(result, key=lambda s: s.start)
