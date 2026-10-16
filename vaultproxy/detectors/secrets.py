import re

from vaultproxy.detectors import Span

# Cloud & Source Control Tokens
AKIA_REGEX = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
ASIA_REGEX = re.compile(r"\bASIA[0-9A-Z]{16}\b")
GHP_REGEX = re.compile(r"\bghp_[a-zA-Z0-9]{36}\b")
GITHUB_PAT_REGEX = re.compile(r"\bgithub_pat_[a-zA-Z0-9_]+\b")
GITHUB_OTHER_REGEX = re.compile(r"\b(?:gho|ghs|ghu|ghr)_[a-zA-Z0-9]{36}\b")
GITLAB_PAT_REGEX = re.compile(r"\bglpat-[0-9a-zA-Z_\-]{20,}\b")
JWT_REGEX = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")

# AI & SaaS Provider Keys
OPENAI_REGEX = re.compile(r"\bsk-(?:proj-|admin-)?[a-zA-Z0-9_\-]{20,}\b")
ANTHROPIC_REGEX = re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b")
GOOGLE_API_KEY_REGEX = re.compile(r"\bAIza[0-9A-Za-z\-_]{30,}\b")
STRIPE_REGEX = re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,}\b")
SLACK_TOKEN_REGEX = re.compile(
    r"\bxox[baprs]-[0-9a-zA-Z]{10,48}-[0-9a-zA-Z]{10,48}-[0-9a-zA-Z]{24,32}\b"
)
SLACK_WEBHOOK_REGEX = re.compile(
    r"https:\/\/hooks\.slack\.com\/services\/T[0-9A-Z_]+\/B[0-9A-Z_]+\/[0-9a-zA-Z_]+"
)
HUGGINGFACE_REGEX = re.compile(r"\bhf_[a-zA-Z0-9]{34,}\b")
PYPI_TOKEN_REGEX = re.compile(r"\bpypi-AgEIcHlwaS5vcmc[a-zA-Z0-9_\-]{50,}\b")
NPM_TOKEN_REGEX = re.compile(r"\bnpm_[a-zA-Z0-9_]{32,40}\b")
SENDGRID_REGEX = re.compile(r"\bSG\.[a-zA-Z0-9_\-\.]{32,80}\b")
TWILIO_REGEX = re.compile(r"\bSK[0-9a-fA-F]{32}\b")
SENTRY_DSN_REGEX = re.compile(r"\bhttps:\/\/[a-f0-9]{32}@[a-zA-Z0-9_\.\-]+\/[0-9]+\b")

# Infrastructure & Private Keys
PRIVATE_KEY_REGEX = re.compile(
    r"-----BEGIN (?:[A-Z0-9_\- ]+ )?PRIVATE KEY(?: BLOCK)?-----"
    r"[\s\S]*?"
    r"-----END (?:[A-Z0-9_\- ]+ )?PRIVATE KEY(?: BLOCK)?-----"
)
OPENSSH_KEY_REGEX = re.compile(
    r"-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]*?-----END OPENSSH PRIVATE KEY-----"
)
PGP_PRIVATE_KEY_REGEX = re.compile(
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----[\s\S]*?-----END PGP PRIVATE KEY BLOCK-----"
)

# Database & Cache Connection Strings
CONNECTION_STRING_REGEX = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis[s]?|amqp[s]?|mssql|mariadb|clickhouse|snowflake):\/\/[^\s\n\r\"'<>]+(?<![.,;:!?)])",
    re.IGNORECASE,
)

# Bearer Authorization Token
BEARER_TOKEN_REGEX = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9_\-\.]{24,})\b")

# AWS Secret Access Key key-value pattern
AWS_SECRET_KEY_REGEX = re.compile(
    r"(?i)\b(?:aws_secret_access_key|aws_secret_key|secret_access_key)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
)

# Environment Variable & DevOps Config Key-Value Line Pattern
ENV_LINE_REGEX = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:export[ \t]+|ENV[ \t]+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)[ \t]*[:=][ \t]*)(?P<val>[^\r\n]*)"
)

SENSITIVE_WORDS = {
    "SECRET",
    "SECRETS",
    "TOKEN",
    "TOKENS",
    "PASS",
    "PASSWORD",
    "PASSWORDS",
    "PASSWD",
    "PWD",
    "CREDENTIAL",
    "CREDENTIALS",
    "PRIVATE",
    "SIGNING",
    "SALT",
    "APIKEY",
    "DSN",
    "PASSPHRASE",
    "ENCRYPTION",
    "BEARER",
}

AUTH_WORDS = {"AUTH", "AUTHENTICATION", "AUTHORIZATION", "OAUTH"}

SENSITIVE_COMPOUNDS = (
    "DATABASE_URL",
    "DB_URL",
    "REDIS_URL",
    "MONGO_URL",
    "AMQP_URL",
    "WEBHOOK",
    "ACCESS_KEY",
    "SECRET_KEY",
    "PRIVATE_KEY",
    "API_KEY",
    "SESSION_SECRET",
    "SIGNING_KEY",
    "SSH_KEY",
    "MASTER_KEY",
)

WORD_TOKEN_PATTERN = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Za-z][a-z0-9]*"
)

TRIVIAL_CONFIG_VALUES = {
    "",
    "true",
    "false",
    "null",
    "none",
    "nil",
    "undefined",
    "0",
    "1",
    "localhost",
    "127.0.0.1",
    "off",
    "on",
    "default",
    "[",
    "]",
    "{",
    "}",
    "(",
    ")",
    ",",
    ";",
}


def is_sensitive_key(key: str) -> bool:
    """Classify whether a configuration or environment variable key holds secrets."""
    key_upper = key.upper()
    if any(c in key_upper for c in SENSITIVE_COMPOUNDS):
        return True
    # Split by underscore, hyphen, or camelCase
    words = set(WORD_TOKEN_PATTERN.findall(key))
    words_upper = {w.upper() for w in words}

    if words_upper & SENSITIVE_WORDS:
        return True
    if words_upper & AUTH_WORDS:
        return True
    if "KEY" in words_upper:
        return True
    if "PIN" in words_upper:
        return True
    if "CERT" in words_upper or "CERTIFICATE" in words_upper:
        return True
    return False


def _detect_env_line_secrets(text: str) -> list[Span]:
    """Detect sensitive credentials leaked inside .env / config / export lines."""
    spans: list[Span] = []
    for match in ENV_LINE_REGEX.finditer(text):
        key = match.group("key")
        if not is_sensitive_key(key):
            continue

        prefix_len = len(match.group("prefix"))
        val_raw = match.group("val")
        val_start_in_text = match.start() + prefix_len

        # Case 1: Double-quoted value
        if val_raw.startswith('"'):
            match_end = re.search(r'(?<!\\)"', val_raw[1:])
            if match_end:
                end_quote_idx = 1 + match_end.start()
                inner_val = val_raw[1:end_quote_idx]
                if inner_val.strip().lower() not in TRIVIAL_CONFIG_VALUES:
                    spans.append(
                        Span(
                            start=val_start_in_text + 1,
                            end=val_start_in_text + end_quote_idx,
                            type="SECRET",
                            source="rule",
                            score=1.0,
                        )
                    )
            continue

        # Case 2: Single-quoted value
        if val_raw.startswith("'"):
            match_end = re.search(r"(?<!\\)'", val_raw[1:])
            if match_end:
                end_quote_idx = 1 + match_end.start()
                inner_val = val_raw[1:end_quote_idx]
                if inner_val.strip().lower() not in TRIVIAL_CONFIG_VALUES:
                    spans.append(
                        Span(
                            start=val_start_in_text + 1,
                            end=val_start_in_text + end_quote_idx,
                            type="SECRET",
                            source="rule",
                            score=1.0,
                        )
                    )
            continue

        # Case 3: Unquoted value (strip inline comments # ...)
        val_clean = val_raw.split("#")[0].rstrip()
        leading_ws = len(val_clean) - len(val_clean.lstrip())
        val_clean = val_clean.lstrip()
        bearer_offset = 0
        if val_clean.lower().startswith("bearer ") and len(val_clean) > 7:
            bearer_offset = len("bearer ")
            val_clean = val_clean[bearer_offset:]

        if val_clean.strip().lower() not in TRIVIAL_CONFIG_VALUES:
            spans.append(
                Span(
                    start=val_start_in_text + leading_ws + bearer_offset,
                    end=val_start_in_text + leading_ws + bearer_offset + len(val_clean),
                    type="SECRET",
                    source="rule",
                    score=1.0,
                )
            )

    return spans


def detect_secrets(text: str) -> list[Span]:
    """Run all secrets detectors on text: tokens, keys, certs, DB URIs, and
    .env lines."""
    spans: list[Span] = []

    # 1. Direct Regex Pattern Matching
    direct_patterns = (
        AKIA_REGEX,
        ASIA_REGEX,
        GHP_REGEX,
        GITHUB_PAT_REGEX,
        GITHUB_OTHER_REGEX,
        GITLAB_PAT_REGEX,
        JWT_REGEX,
        OPENAI_REGEX,
        ANTHROPIC_REGEX,
        GOOGLE_API_KEY_REGEX,
        STRIPE_REGEX,
        SLACK_TOKEN_REGEX,
        SLACK_WEBHOOK_REGEX,
        HUGGINGFACE_REGEX,
        PYPI_TOKEN_REGEX,
        NPM_TOKEN_REGEX,
        SENDGRID_REGEX,
        TWILIO_REGEX,
        SENTRY_DSN_REGEX,
        PRIVATE_KEY_REGEX,
        OPENSSH_KEY_REGEX,
        PGP_PRIVATE_KEY_REGEX,
        CONNECTION_STRING_REGEX,
    )

    for regex in direct_patterns:
        for match in regex.finditer(text):
            spans.append(
                Span(
                    start=match.start(),
                    end=match.end(),
                    type="SECRET",
                    source="rule",
                    score=1.0,
                )
            )

    # 2. Bearer Authorization Tokens (mask token part only)
    for match in BEARER_TOKEN_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(1),
                end=match.end(1),
                type="SECRET",
                source="rule",
                score=1.0,
            )
        )

    # 3. AWS Secret Access Key patterns (mask key value only)
    for match in AWS_SECRET_KEY_REGEX.finditer(text):
        spans.append(
            Span(
                start=match.start(1),
                end=match.end(1),
                type="SECRET",
                source="rule",
                score=1.0,
            )
        )

    # 4. Environment Variables / Config Line Secrets
    spans.extend(_detect_env_line_secrets(text))

    return spans

