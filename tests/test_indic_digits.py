from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.detectors.verhoeff import generate_verhoeff
from vaultproxy.vault import RequestVault


def test_bengali_aadhaar_and_mobile_detection():
    # Construct valid Aadhaar prefix & check digit
    prefix = "36759834120"
    check = generate_verhoeff(prefix)
    ascii_aadhaar = prefix + str(check)  # 367598341203

    # Map to Bengali digits: 3->৩, 6->৬, 7->৭, 5->৫, 9->৯, 8->৮, 4->৪, 1->১, 2->২, 0->০
    bengali_digit_map = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
    bengali_aadhaar = ascii_aadhaar.translate(bengali_digit_map)
    bengali_mobile = "৯৮Nz-৪৩২১০".replace("Nz", "৭৬৫")  # ৯৮৭৬৫ ৪৩২১০

    text = f"আমার আধার নম্বর {bengali_aadhaar} এবং মোবাইল {bengali_mobile}।"

    spans = run_rule_detectors(text)
    assert len(spans) == 2

    # Check span boundaries on original text
    aadhaar_span = [s for s in spans if s.type == "AADHAAR"][0]
    mobile_span = [s for s in spans if s.type == "MOBILE"][0]

    assert text[aadhaar_span.start : aadhaar_span.end] == bengali_aadhaar
    assert text[mobile_span.start : mobile_span.end] == bengali_mobile

    # Verify masking replaces original Bengali text correctly
    vault = RequestVault()
    masked = vault.mask_text(text, spans)
    assert "[AADHAAR_1]" in masked
    assert "[MOBILE_1]" in masked
    assert bengali_aadhaar not in masked


def test_devanagari_aadhaar_and_mobile_detection():
    prefix = "36759834120"
    check = generate_verhoeff(prefix)
    ascii_aadhaar = prefix + str(check)

    devanagari_digit_map = str.maketrans("0123456789", "०१२३४५६७८९")
    devanagari_aadhaar = ascii_aadhaar.translate(devanagari_digit_map)
    devanagari_mobile = "९८७६५४३२१०"

    text = f"मेरा आधार {devanagari_aadhaar} और मोबाइल {devanagari_mobile} है।"

    spans = run_rule_detectors(text)
    assert len(spans) == 2

    aadhaar_span = [s for s in spans if s.type == "AADHAAR"][0]
    mobile_span = [s for s in spans if s.type == "MOBILE"][0]

    assert text[aadhaar_span.start : aadhaar_span.end] == devanagari_aadhaar
    assert text[mobile_span.start : mobile_span.end] == devanagari_mobile
