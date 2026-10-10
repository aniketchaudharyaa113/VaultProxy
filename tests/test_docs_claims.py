import os

FORBIDDEN_PHRASES = [
    "guarantee",
    "zero-trust",
    "100% safe",
    "ensures compliance",
    "military",
    "high-performance",
]

EXCLUDED_FILES = {
    "docs/HARDENING_PLAN.md",
    "docs/PROGRESS.md",
    "CHANGELOG.md",
}


def test_docs_and_readme_no_unmeasured_claims():
    """Verify README.md and docs/ contain no unmeasured claim wording."""
    files_to_check: list[str] = []

    if os.path.exists("README.md"):
        files_to_check.append("README.md")

    if os.path.exists("docs"):
        for root, _, files in os.walk("docs"):
            for file in files:
                if file.endswith(".md"):
                    rel_path = os.path.relpath(os.path.join(root, file), ".")
                    if rel_path not in EXCLUDED_FILES:
                        files_to_check.append(rel_path)

    violations = []
    for filepath in files_to_check:
        with open(filepath, encoding="utf-8") as f:
            content = f.read().lower()
            for phrase in FORBIDDEN_PHRASES:
                if phrase in content:
                    violations.append(f"Forbidden phrase '{phrase}' found in {filepath}")

    assert not violations, f"Unmeasured claims detected in documentation: {violations}"
