from vaultproxy.detectors.aadhaar import detect_aadhaar
from vaultproxy.detectors.email import detect_email
from vaultproxy.detectors.ifsc import detect_ifsc
from vaultproxy.detectors.mobile import detect_mobile
from vaultproxy.detectors.pan import detect_pan
from vaultproxy.detectors.secrets import detect_secrets
from vaultproxy.detectors.upi import detect_upi
from vaultproxy.detectors.verhoeff import generate_verhoeff


def test_aadhaar_detector():
    prefix = "36759834120"
    check = generate_verhoeff(prefix)
    valid_aadhaar = prefix + str(check)

    formatted_aadhaar = f"{valid_aadhaar[:4]} {valid_aadhaar[4:8]} {valid_aadhaar[8:]}"

    text = f"My Aadhaar is {valid_aadhaar} and formatted {formatted_aadhaar}"
    spans = detect_aadhaar(text)
    assert len(spans) == 2
    assert all(s.type == "AADHAAR" for s in spans)


def test_aadhaar_negative_cases():
    bad_prefix = "12345678901"
    check = generate_verhoeff(bad_prefix)
    order_id = bad_prefix + str(check)

    invalid_check = "367598341209"

    text = f"Order ID is {order_id} and invalid aadhaar is {invalid_check}"
    spans = detect_aadhaar(text)
    assert len(spans) == 0


def test_pan_detector():
    # 4th letter MUST be in P, C, H, F, A, T, B, L, J, G
    text = "Valid PANs: ABCPB1234F, XYZPH9876K. Invalid: ABCXX1234F"
    spans = detect_pan(text)
    assert len(spans) == 2
    assert text[spans[0].start : spans[0].end] == "ABCPB1234F"
    assert text[spans[1].start : spans[1].end] == "XYZPH9876K"


def test_mobile_detector():
    text = "Call me at +91 98765 43210 or 09876543210 or 98765-43210. Ignore 1234567890."
    spans = detect_mobile(text)
    assert len(spans) == 3


def test_upi_detector():
    text = "Pay via user@oksbi or dev@ybl. Email user@example.com is not UPI."
    spans = detect_upi(text)
    assert len(spans) == 2
    assert text[spans[0].start : spans[0].end] == "user@oksbi"
    assert text[spans[1].start : spans[1].end] == "dev@ybl"


def test_ifsc_detector():
    text = "Bank IFSC code is SBIN0001234. Bad code SBIN1001234."
    spans = detect_ifsc(text)
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == "SBIN0001234"


def test_email_detector():
    text = "Contact support@example.co.in for help."
    spans = detect_email(text)
    assert len(spans) == 1
    assert text[spans[0].start : spans[0].end] == "support@example.co.in"


def test_secrets_detector():
    text = (
        "AWS: AKIAIOSFODNN7EXAMPLE, "
        "GH: ghp_1234567890abcdefghijklmnopqrstuvwxyz, "
        "PAT: github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789, "
        "JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    spans = detect_secrets(text)
    assert len(spans) == 4
