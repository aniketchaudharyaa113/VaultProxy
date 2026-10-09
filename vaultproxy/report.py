import json
from typing import Any


def create_vault_report_header(
    masked_counts: dict[str, int], degraded: bool, gemma_used: bool
) -> str:
    """Create JSON string for X-Vault-Report header containing entity type counts only."""
    report: dict[str, Any] = {
        "masked": masked_counts,
        "degraded": degraded,
        "gemma_used": gemma_used,
    }
    return json.dumps(report)
