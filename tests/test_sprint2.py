from vaultproxy.detectors import Span
from vaultproxy.restore import StreamRestorer, restore_text
from vaultproxy.vault import RequestVault


def test_vault_mask_and_restore():
    vault = RequestVault()

    text = "My PAN is ABCPB1234F and mobile is 9876543210. Repeat PAN: ABCPB1234F."
    spans = [
        Span(start=10, end=20, type="PAN", source="rule"),
        Span(start=35, end=45, type="MOBILE", source="rule"),
        Span(start=59, end=69, type="PAN", source="rule"),
    ]

    masked = vault.mask_text(text, spans)
    assert "[PAN_1]" in masked
    assert "[MOBILE_1]" in masked
    assert masked == "My PAN is [PAN_1] and mobile is [MOBILE_1]. Repeat PAN: [PAN_1]."

    restored = restore_text(masked, vault)
    assert restored == text


def test_stream_restorer_split_every_char():
    vault = RequestVault()
    text = "Hello ABCPB1234F, your mobile is 9876543210."
    spans = [
        Span(start=6, end=16, type="PAN", source="rule"),
        Span(start=33, end=43, type="MOBILE", source="rule"),
    ]
    masked = vault.mask_text(text, spans)
    expected_restored = restore_text(masked, vault)

    for i in range(len(masked) + 1):
        chunk1 = masked[:i]
        chunk2 = masked[i:]

        restorer = StreamRestorer(vault)
        out1 = restorer.feed(chunk1)
        out2 = restorer.feed(chunk2)
        out3 = restorer.flush()

        combined = out1 + out2 + out3
        assert combined == expected_restored, f"Failed at split index {i}"


def test_stream_restorer_token_split_across_chunks():
    vault = RequestVault()
    vault.value_to_token["ABCPB1234F"] = "[PAN_1]"
    vault.token_to_value["[PAN_1]"] = "ABCPB1234F"

    restorer = StreamRestorer(vault)
    out1 = restorer.feed("Hello [PAN_")
    out2 = restorer.feed("1] world")
    out3 = restorer.flush()

    assert out1 == "Hello "
    assert out2 == "ABCPB1234F world"
    assert out3 == ""
    assert out1 + out2 + out3 == "Hello ABCPB1234F world"


def test_stream_restorer_bracket_not_a_token():
    vault = RequestVault()
    vault.value_to_token["ABCPB1234F"] = "[PAN_1]"
    vault.token_to_value["[PAN_1]"] = "ABCPB1234F"

    restorer = StreamRestorer(vault)
    out1 = restorer.feed("[Note] this is [not a token] [PAN_1]")
    out2 = restorer.flush()

    assert out1 == "[Note] this is [not a token] ABCPB1234F"
    assert out2 == ""


def test_stream_restorer_no_tokens():
    vault = RequestVault()
    restorer = StreamRestorer(vault)
    out1 = restorer.feed("Plain text with no tokens")
    out2 = restorer.flush()

    assert out1 == "Plain text with no tokens"
    assert out2 == ""
