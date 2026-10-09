from vaultproxy.detectors import Span
from vaultproxy.detectors.aadhaar import detect_aadhaar
from vaultproxy.detectors.email import detect_email
from vaultproxy.detectors.ifsc import detect_ifsc
from vaultproxy.detectors.indic import normalize_indic_digits
from vaultproxy.detectors.mobile import detect_mobile
from vaultproxy.detectors.pan import detect_pan
from vaultproxy.detectors.secrets import detect_secrets
from vaultproxy.detectors.upi import detect_upi


def run_rule_detectors(text: str) -> list[Span]:
    """Run all rule-based detectors on text after Indic numeral normalization."""
    normalized_text = normalize_indic_digits(text)

    spans: list[Span] = []
    spans.extend(detect_aadhaar(normalized_text))
    spans.extend(detect_pan(normalized_text))
    spans.extend(detect_mobile(normalized_text))
    spans.extend(detect_upi(normalized_text))
    spans.extend(detect_ifsc(normalized_text))
    spans.extend(detect_email(normalized_text))
    spans.extend(detect_secrets(normalized_text))
    return spans
