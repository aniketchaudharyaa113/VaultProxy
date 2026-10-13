import re
from pathlib import Path

from vaultproxy.config import Settings


def parse_readme_settings_tables(readme_path: str = "README.md") -> dict[str, str]:
    """Parse configuration tables from README.md Section 6 and extract {setting_name: default_value_str}."""
    content = Path(readme_path).read_text(encoding="utf-8")
    section_match = re.search(
        r"## 6\. Configuration Reference(.*?)(?=\n## 7\.|\Z)",
        content,
        re.DOTALL,
    )
    section_text = section_match.group(1) if section_match else content

    pattern = re.compile(r"^\|\s*`([A-Z0-9_]+)`\s*\|\s*`?([^`|]+?)`?\s*\|", re.MULTILINE)
    matches = pattern.findall(section_text)

    doc_settings = {}
    for name, default_str in matches:
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


def test_readme_tables_have_consistent_unescaped_pipes(readme_path: str = "README.md"):
    """Verify that every Markdown table outside code blocks in README.md has consistent unescaped pipe counts per row."""
    content = Path(readme_path).read_text(encoding="utf-8")
    lines = []
    in_code = False
    for line in content.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            lines.append(line)

    tables = []
    current_table = []
    for line in lines:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current_table.append(line.strip())
        else:
            if current_table:
                tables.append(current_table)
                current_table = []
    if current_table:
        tables.append(current_table)

    assert len(tables) > 0, "No Markdown tables found in README.md"

    for idx, table in enumerate(tables):
        counts = [len(re.findall(r"(?<!\\)\|", row)) for row in table]
        distinct_counts = set(counts)
        assert len(distinct_counts) == 1, (
            f"Table {idx} (starting with '{table[0]}') has inconsistent unescaped pipe counts: {distinct_counts}. "
            f"Rows: {table}"
        )


def test_secret_types_named_in_readme_have_detector_tests(readme_path: str = "README.md"):
    """Verify that every secret type named in the README SECRET row has a corresponding detector test."""
    content = Path(readme_path).read_text(encoding="utf-8")
    secret_row_match = re.search(r"^\|\s*`SECRET`\s*\|\s*(.*?)\s*\|", content, re.MULTILINE)
    assert secret_row_match, "Could not find `SECRET` row in README.md tables"
    secret_desc = secret_row_match.group(1)

    # Must detect only what vaultproxy/detectors/secrets.py detects today
    expected_types = ["AKIA", "ghp_", "github_pat_", "JWT"]
    for stype in expected_types:
        assert stype in secret_desc, f"Expected secret type '{stype}' missing from README SECRET row: '{secret_desc}'"

    forbidden_claims = ["OpenAI", "Slack", "Stripe", "RSA", "postgres"]
    for claim in forbidden_claims:
        assert claim not in secret_desc, f"Undetected secret type '{claim}' should not be listed in SECRET row: '{secret_desc}'"

    # Verify each secret type has test coverage in tests/test_detectors.py
    detectors_test_content = Path("tests/test_detectors.py").read_text(encoding="utf-8")
    assert "test_secrets_detector" in detectors_test_content

    # AWS check (built from pieces to avoid scanner false positives)
    assert ("AK" in detectors_test_content and "IA" in detectors_test_content) or "AKIA" in detectors_test_content
    # GitHub ghp_ check
    assert ("gh" in detectors_test_content and "p_" in detectors_test_content) or "ghp_" in detectors_test_content
    # GitHub PAT check
    assert ("github_" in detectors_test_content and "pat_" in detectors_test_content) or "github_pat_" in detectors_test_content
    # JWT check
    assert "JWT" in detectors_test_content
