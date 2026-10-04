# Contributing to VaultProxy 🛠️

Thank you for contributing! VaultProxy follows strict local-first privacy principles and Agile development.

## Guidelines

1. **Fail-Closed Principle**: Never change error-handling behavior to expose raw PII. Any unexpected error in detection or masking MUST return HTTP 503 and forward nothing.
2. **Zero PII in Logs**: Logs may contain entity types and counts only. Never log raw prompts, replies, or detected values.
3. **Fake Test Data Only**: All test data must be synthetic and fake.

## Adding a New Detector in 2 Steps

### Step 1: Create Detector File
Add your detector in `vaultproxy/detectors/<entity_name>.py`:

```python
import re
from typing import List
from vaultproxy.detectors import Span

MY_ENTITY_REGEX = re.compile(r"\bMYID-\d{6}\b")

def detect_my_entity(text: str) -> List[Span]:
    spans: List[Span] = []
    for match in MY_ENTITY_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(),
                end=match.end(),
                type="MY_ENTITY",
                source="rule",
                score=1.0,
            )
        )
    return spans
```

Register your function inside `vaultproxy/detectors/registry.py`:

```python
from vaultproxy.detectors.my_entity import detect_my_entity

def run_rule_detectors(text: str) -> List[Span]:
    # ...
    spans.extend(detect_my_entity(text))
    return spans
```

### Step 2: Add Unit Tests
Add test cases in `tests/test_detectors.py`:

```python
def test_my_entity_detector():
    text = "My ID is MYID-123456"
    spans = detect_my_entity(text)
    assert len(spans) == 1
    assert spans[0].type == "MY_ENTITY"
```

## Running Tests & Smoke Verification

Before submitting a pull request, run:

```bash
# Run pytest test suite
python3 -m pytest -v

# Run smoke test script
./scripts/smoke.sh
```
