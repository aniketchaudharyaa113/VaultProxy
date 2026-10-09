# Indic numeral 1-to-1 Unicode normalization to ASCII 0-9

INDIC_DIGIT_MAP = str.maketrans(
    {
        # Devanagari (\u0966 - \u096F)
        "\u0966": "0",
        "\u0967": "1",
        "\u0968": "2",
        "\u0969": "3",
        "\u096a": "4",
        "\u096b": "5",
        "\u096c": "6",
        "\u096d": "7",
        "\u096e": "8",
        "\u096f": "9",
        # Bengali (\u09E6 - \u09EF)
        "\u09e6": "0",
        "\u09e7": "1",
        "\u09e8": "2",
        "\u09e9": "3",
        "\u09ea": "4",
        "\u09eb": "5",
        "\u09ec": "6",
        "\u09ed": "7",
        "\u09ee": "8",
        "\u09ef": "9",
        # Gurmukhi (\u0A66 - \u0A6F)
        "\u0a66": "0",
        "\u0a67": "1",
        "\u0a68": "2",
        "\u0a69": "3",
        "\u0a6a": "4",
        "\u0a6b": "5",
        "\u0a6c": "6",
        "\u0a6d": "7",
        "\u0a6e": "8",
        "\u0a6f": "9",
        # Gujarati (\u0AE6 - \u0AEF)
        "\u0ae6": "0",
        "\u0ae7": "1",
        "\u0ae8": "2",
        "\u0ae9": "3",
        "\u0aea": "4",
        "\u0aeb": "5",
        "\u0aec": "6",
        "\u0aed": "7",
        "\u0aee": "8",
        "\u0aef": "9",
        # Odia (\u0B66 - \u0B6F)
        "\u0b66": "0",
        "\u0b67": "1",
        "\u0b68": "2",
        "\u0b69": "3",
        "\u0b6a": "4",
        "\u0b6b": "5",
        "\u0b6c": "6",
        "\u0b6d": "7",
        "\u0b6e": "8",
        "\u0b6f": "9",
        # Tamil (\u0BE6 - \u0BEF)
        "\u0be6": "0",
        "\u0be7": "1",
        "\u0be8": "2",
        "\u0be9": "3",
        "\u0bea": "4",
        "\u0beb": "5",
        "\u0bec": "6",
        "\u0bed": "7",
        "\u0bee": "8",
        "\u0bef": "9",
        # Telugu (\u0C66 - \u0C6F)
        "\u0c66": "0",
        "\u0c67": "1",
        "\u0c68": "2",
        "\u0c69": "3",
        "\u0c6a": "4",
        "\u0c6b": "5",
        "\u0c6c": "6",
        "\u0c6d": "7",
        "\u0c6e": "8",
        "\u0c6f": "9",
        # Kannada (\u0CE6 - \u0CEF)
        "\u0ce6": "0",
        "\u0ce7": "1",
        "\u0ce8": "2",
        "\u0ce9": "3",
        "\u0cea": "4",
        "\u0ceb": "5",
        "\u0cec": "6",
        "\u0ced": "7",
        "\u0cee": "8",
        "\u0cef": "9",
        # Malayalam (\u0D66 - \u0D6F)
        "\u0d66": "0",
        "\u0d67": "1",
        "\u0d68": "2",
        "\u0d69": "3",
        "\u0d6a": "4",
        "\u0d6b": "5",
        "\u0d6c": "6",
        "\u0d6d": "7",
        "\u0d6e": "8",
        "\u0d6f": "9",
    }
)


def normalize_indic_digits(text: str) -> str:
    """Map Indic Unicode decimal digits to ASCII 0-9 1-to-1 preserving exact offsets."""
    if not text:
        return text
    return text.translate(INDIC_DIGIT_MAP)
