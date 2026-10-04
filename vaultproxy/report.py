import json
from typing import Dict, Any


def create_vault_report_header(
    masked_counts: Dict[str, int], degraded: bool, gemma_used: bool
) -> str:
    report: Dict[str, Any] = {
        "masked": masked_counts,
        "degraded": degraded,
        "gemma_used": gemma_used,
    }
    return json.dumps(report)
