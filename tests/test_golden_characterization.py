"""Golden characterization test suite freezing current VaultProxy behaviour.

Covers:
- Masking outputs for 40+ fake inputs across all entity types
- Response headers (X-Vault-Report header output)
- Streaming output for split points (split-at-every-position test)
- Strict-mode vs non-strict mode outcomes
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from vaultproxy.config import settings
from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.gemma_layer import GemmaLayerError
from vaultproxy.report import create_vault_report_header
from vaultproxy.restore import StreamRestorer, restore_text
from vaultproxy.server import app
from vaultproxy.vault import RequestVault

GOLDEN_TEST_INPUTS = [
    # Aadhaar (Verhoeff valid)
    ("My Aadhaar is 367598341203 please verify", "[AADHAAR_1]", "367598341203"),
    ("Aadhaar: 999999990019 is valid", "[AADHAAR_1]", "999999990019"),
    ("Contact with Aadhaar 3675-9834-1203 here", "[AADHAAR_1]", "3675-9834-1203"),
    ("Aadhaar formatted 9999 9999 0019 test", "[AADHAAR_1]", "9999 9999 0019"),
    ("Aadhaar 567812349012 valid verhoeff", "567812349012", None), # invalid verhoeff test
    # Aadhaar (Invalid Verhoeff - should NOT mask as Aadhaar)
    ("Invalid Aadhaar 123456789012 should fail checksum", "123456789012", None),
    ("All zeros 000000000000 invalid", "000000000000", None),

    # PAN
    ("My PAN is ABCPB1234F thanks", "[PAN_1]", "ABCPB1234F"),
    ("PAN number: XYZPD5678K", "[PAN_1]", "XYZPD5678K"),
    ("PAN ABCPB1234F and second PAN XYZPD5678K", "[PAN_1]", "ABCPB1234F"),
    ("PAN format testing PAAAP9999L", "[PAN_1]", "PAAAP9999L"),
    ("Invalid PAN layout ABC123456F should skip", "ABC123456F", None),

    # Mobile
    ("Mobile number is 9876543210", "[MOBILE_1]", "9876543210"),
    ("Phone +91 9876543210 call me", "[MOBILE_1]", "+91 9876543210"),
    ("Call +91-9876543210 or 8765432109", "[MOBILE_1]", "+91-9876543210"),
    ("Mobile with 0 prefix 09876543210 test", "[MOBILE_1]", "09876543210"),
    ("Short number 12345 invalid", "12345", None),

    # UPI ID
    ("Pay me at user@okaxis", "[UPI_ID_1]", "user@okaxis"),
    ("UPI ID shop@paytm for transaction", "[UPI_ID_1]", "shop@paytm"),
    ("Send to name@oksbi now", "[UPI_ID_1]", "name@oksbi"),
    ("VPA merchant@okhdfcbank valid", "[UPI_ID_1]", "merchant@okhdfcbank"),
    ("VPA john.doe@ybl active", "[UPI_ID_1]", "john.doe@ybl"),
    ("VPA customer@ibl active", "[UPI_ID_1]", "customer@ibl"),
    ("VPA user@axl active", "[UPI_ID_1]", "user@axl"),

    # IFSC
    ("Bank IFSC is SBIN0001234", "[IFSC_1]", "SBIN0001234"),
    ("IFSC code HDFC0005678 branch", "[IFSC_1]", "HDFC0005678"),
    ("Code ICIC0001122 active", "[IFSC_1]", "ICIC0001122"),
    ("Invalid IFSC SBIN1123456 (5th char not zero) should fail", "SBIN1123456", None),

    # Email
    ("Email me at user@example.com", "[EMAIL_1]", "user@example.com"),
    ("Contact support@company.co.in today", "[EMAIL_1]", "support@company.co.in"),
    ("Email test.user+tag@domain.org valid", "[EMAIL_1]", "test.user+tag@domain.org"),
    ("Admin admin@sub.domain.com active", "[EMAIL_1]", "admin@sub.domain.com"),

    # Secrets
    ("AWS Key AKIAIOSFODNN7EXAMPLE", "[SECRET_1]", "AKIAIOSFODNN7EXAMPLE"),
    ("GitHub token ghp_1234567890abcdefghijklmnopqrstuvwxyz", "[SECRET_1]", "ghp_1234567890abcdefghijklmnopqrstuvwxyz"),
    ("GitHub PAT github_pat_11AAAAAAA01234567890_abcdefghijklmnopqrstuvwxyz", "[SECRET_1]", "github_pat_11AAAAAAA01234567890_abcdefghijklmnopqrstuvwxyz"),
    ("JWT token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "[SECRET_1]", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),

    # Indic digits normalisation
    ("Devanagari Aadhaar: ३६७५९८३४१२०३ valid", "[AADHAAR_1]", "३६७५९८३४१२०३"),
    ("Gurmukhi Mobile: ੯੮੭੬੫੪੩੨੧੦ valid", "[MOBILE_1]", "੯੮੭੬੫੪੩੨੧੦"),
    ("Bengali Mobile: ৯ODG 9876543210 test", "[MOBILE_1]", "9876543210"),
    ("Gujarati Mobile: ૯૮૭૬૫૪૩૨૧૦ test", "[MOBILE_1]", "૯૮૭૬૫૪૩૨૧૦"),

    # Mixed & Multi-entity
    ("User user@example.com with PAN ABCPB1234F and phone 9876543210", "[EMAIL_1]", "user@example.com"),
    ("Aadhaar 367598341203 and IFSC SBIN0001234 plus UPI pay@ybl", "[AADHAAR_1]", "367598341203"),
    ("Same PAN twice: ABCPB1234F and ABCPB1234F", "[PAN_1]", "ABCPB1234F"),
    ("Multiple distinct emails a@b.com and c@d.com", "[EMAIL_1]", "a@b.com"),
    ("Plain text input without any sensitive entities", "Plain text input without any sensitive entities", None),
    ("Empty string input testing", "Empty string input testing", None),
    ("Special characters !@#$%^&*() input without PII", "Special characters !@#$%^&*() input without PII", None),
]


@pytest.mark.parametrize("input_text, expected_token_or_text, raw_val", GOLDEN_TEST_INPUTS)
def test_golden_masking_characterization(input_text, expected_token_or_text, raw_val):
    vault = RequestVault()
    spans = run_rule_detectors(input_text)
    masked = vault.mask_text(input_text, spans)

    if raw_val is not None:
        assert expected_token_or_text in masked, f"Expected {expected_token_or_text} in masked string '{masked}'"
        assert raw_val not in masked, f"Raw value '{raw_val}' must not be present in masked string '{masked}'"
        restored = restore_text(masked, vault)
        assert raw_val in restored, f"Restored text '{restored}' must contain raw value '{raw_val}'"
    else:
        assert masked == input_text, f"Input without sensitive data should remain unchanged: '{masked}'"


def test_golden_vault_report_header_schema():
    counts = {"AADHAAR": 2, "PAN": 1, "MOBILE": 3}
    header = create_vault_report_header(counts, degraded=False, gemma_used=True)
    parsed = json.loads(header)

    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {"masked", "degraded", "gemma_used"}
    assert parsed["masked"] == {"AADHAAR": 2, "PAN": 1, "MOBILE": 3}
    assert parsed["degraded"] is False
    assert parsed["gemma_used"] is True


def test_golden_streaming_split_every_position():
    vault = RequestVault()
    text = "Important: PAN is ABCPB1234F, Aadhaar is 367598341203, Email is test@example.com."
    spans = run_rule_detectors(text)
    masked = vault.mask_text(text, spans)
    expected_restored = restore_text(masked, vault)

    for split_idx in range(len(masked) + 1):
        chunk_a = masked[:split_idx]
        chunk_b = masked[split_idx:]

        restorer = StreamRestorer(vault)
        out_a = restorer.feed(chunk_a)
        out_b = restorer.feed(chunk_b)
        out_final = restorer.flush()

        combined = out_a + out_b + out_final
        assert combined == expected_restored, f"Streaming restoration failed at split index {split_idx}"


def test_golden_strict_mode_outcomes():
    client = TestClient(app)

    payload = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "My PAN is ABCPB1234F"}],
    }

    # Strict mode OFF + Gemma error => 503 fail closed on server endpoint exception
    with patch.object(settings, "STRICT_MODE", False):
        with patch("vaultproxy.masking.run_gemma_detection", side_effect=GemmaLayerError("Gemma down")):
            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 503

    # Strict mode ON + Gemma error => 503 fail closed
    with patch.object(settings, "STRICT_MODE", True):
        with patch("vaultproxy.masking.run_gemma_detection", side_effect=GemmaLayerError("Gemma down")):
            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 503
            assert "VaultProxy fail-closed" in resp.json()["detail"]
