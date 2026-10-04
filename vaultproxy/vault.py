from typing import Dict
from vaultproxy.detectors import Span


class RequestVault:

    def __init__(self):
        self.value_to_token: Dict[str, str] = {}
        self.token_to_value: Dict[str, str] = {}
        self.type_counts: Dict[str, int] = {}

    def get_or_create_token(self, value: str, entity_type: str) -> str:
        if value in self.value_to_token:
            return self.value_to_token[value]

        count = self.type_counts.get(entity_type, 0) + 1
        self.type_counts[entity_type] = count
        token = f"[{entity_type}_{count}]"

        self.value_to_token[value] = token
        self.token_to_value[token] = value
        return token
