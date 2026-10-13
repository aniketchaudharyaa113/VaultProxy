import re
from pathlib import Path

from vaultproxy.config import Settings


def parse_readme_settings_tables(readme_path: str = "README.md") -> dict[str, str]:
    """Parse configuration tables from README.md and extract {setting_name: default_value_str}."""
    content = Path(readme_path).read_text(encoding="utf-8")

    # Match rows like: | `NAME` | `DEFAULT` | MEANING |
    # or | `NAME` | DEFAULT | MEANING |
    pattern = re.compile(r"^\|\s*`([A-Z0-9_]+)`\s*\|\s*`?([^`|]+?)`?\s*\|", re.MULTILINE)
    matches = pattern.findall(content)

    doc_settings = {}
    for name, default_str in matches:
        # Ignore header rows if any matched
        if name in ("NAME", "SETTING"):
            continue
        doc_settings[name] = default_str.strip()

    return doc_settings


def test_docs_settings_match_code():
    """Ensure every Setting defined in vaultproxy.config.Settings is documented in README.md

    with exact matching default values, and no unknown settings exist in the documentation.
    """
    doc_settings = parse_readme_settings_tables("README.md")
    code_fields = Settings.model_fields

    # 1. Check all code settings are documented
    missing_in_docs = set(code_fields.keys()) - set(doc_settings.keys())
    assert not missing_in_docs, f"Settings defined in code but missing in README.md: {missing_in_docs}"

    # 2. Check no extra settings documented that don't exist in code
    extra_in_docs = set(doc_settings.keys()) - set(code_fields.keys())
    assert not extra_in_docs, f"Settings documented in README.md but not in code: {extra_in_docs}"

    # 3. Check default values match
    mismatches = []
    for name, field in code_fields.items():
        doc_default = doc_settings[name]
        code_default = field.default

        # Normalize string representation of default
        if code_default == "":
            expected_str = '""'
        elif isinstance(code_default, bool):
            expected_str = str(code_default)
        elif isinstance(code_default, (int, float)):
            expected_str = str(code_default)
        else:
            expected_str = str(code_default)

        # Allow empty quotes or literal value representation
        if doc_default != expected_str and doc_default.strip('"`') != expected_str.strip('"`'):
            mismatches.append(f"{name}: doc default '{doc_default}' != code default '{expected_str}'")

    assert not mismatches, f"Default value mismatches between README.md and Settings: {mismatches}"
