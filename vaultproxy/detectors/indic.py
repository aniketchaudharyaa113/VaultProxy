# Indic numeral 1-to-1 Unicode normalization to ASCII 0-9

INDIC_DIGIT_MAP = str.maketrans({
    # Devanagari (\u0966 - \u096F)
    '\u0966': '0', '\u0967': '1', '\u0968': '2', '\u0969': '3', '\u096A': '4',
    '\u096B': '5', '\u096C': '6', '\u096D': '7', '\u096E': '8', '\u096F': '9',
    # Bengali (\u09E6 - \u09EF)
    '\u09E6': '0', '\u09E7': '1', '\u09E8': '2', '\u09E9': '3', '\u09EA': '4',
    '\u09EB': '5', '\u09EC': '6', '\u09ED': '7', '\u09EE': '8', '\u09EF': '9',
    # Gurmukhi (\u0A66 - \u0A6F)
    '\u0A66': '0', '\u0A67': '1', '\u0A68': '2', '\u0A69': '3', '\u0A6A': '4',
    '\u0A6B': '5', '\u0A6C': '6', '\u0A6D': '7', '\u0A6E': '8', '\u0A6F': '9',
    # Gujarati (\u0AE6 - \u0AEF)
    '\u0AE6': '0', '\u0AE7': '1', '\u0AE8': '2', '\u0AE9': '3', '\u0AEA': '4',
    '\u0AEB': '5', '\u0AEC': '6', '\u0AED': '7', '\u0AEE': '8', '\u0AEF': '9',
    # Odia (\u0B66 - \u0B6F)
    '\u0B66': '0', '\u0B67': '1', '\u0B68': '2', '\u0B69': '3', '\u0B6A': '4',
    '\u0B6B': '5', '\u0B6C': '6', '\u0B6D': '7', '\u0B6E': '8', '\u0B6F': '9',
    # Tamil (\u0BE6 - \u0BEF)
    '\u0BE6': '0', '\u0BE7': '1', '\u0BE8': '2', '\u0BE9': '3', '\u0BEA': '4',
    '\u0BEB': '5', '\u0BEC': '6', '\u0BED': '7', '\u0BEE': '8', '\u0BEF': '9',
    # Telugu (\u0C66 - \u0C6F)
    '\u0C66': '0', '\u0C67': '1', '\u0C68': '2', '\u0C69': '3', '\u0C6A': '4',
    '\u0C6B': '5', '\u0C6C': '6', '\u0C6D': '7', '\u0C6E': '8', '\u0C6F': '9',
    # Kannada (\u0CE6 - \u0CEF)
    '\u0CE6': '0', '\u0CE7': '1', '\u0CE8': '2', '\u0CE9': '3', '\u0CEA': '4',
    '\u0CEB': '5', '\u0CEC': '6', '\u0CED': '7', '\u0CEE': '8', '\u0CEF': '9',
    # Malayalam (\u0D66 - \u0D6F)
    '\u0D66': '0', '\u0D67': '1', '\u0D68': '2', '\u0D69': '3', '\u0D6A': '4',
    '\u0D6B': '5', '\u0D6C': '6', '\u0D6D': '7', '\u0D6E': '8', '\u0D6F': '9',
})


def normalize_indic_digits(text: str) -> str:
    """Map Indic Unicode decimal digits to ASCII 0-9 1-to-1 preserving exact offsets."""
    if not text:
        return text
    return text.translate(INDIC_DIGIT_MAP)
