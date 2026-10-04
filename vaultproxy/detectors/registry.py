from typing import List
from vaultproxy.detectors import Span
from vaultproxy.detectors.aadhaar import detect_aadhaar
from vaultproxy.detectors.pan import detect_pan
from vaultproxy.detectors.mobile import detect_mobile
from vaultproxy.detectors.upi import detect_upi
from vaultproxy.detectors.ifsc import detect_ifsc
from vaultproxy.detectors.email import detect_email
from vaultproxy.detectors.secrets import detect_secrets


def run_rule_detectors(text: str) -> List[Span]:
    """Run all rule-based detectors on the text and return found spans."""
    spans: List[Span] = []
    spans.extend(detect_aadhaar(text))
    spans.extend(detect_pan(text))
    spans.extend(detect_mobile(text))
    spans.extend(detect_upi(text))
    spans.extend(detect_ifsc(text))
    spans.extend(detect_email(text))
    spans.extend(detect_secrets(text))
    return spans
