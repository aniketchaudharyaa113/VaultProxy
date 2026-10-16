from vaultproxy.detectors.secrets import detect_secrets
from vaultproxy.masking import MaskingEngine
from vaultproxy.restore import restore_text
from vaultproxy.vault import RequestVault


def test_dev_env_file_leak_detection_and_masking():
    """Verify that an entire leaked .env block masks sensitive credentials
    while preserving safe configuration keys."""
    mock_stripe = f"sk_{'live'}_51Abcdefghijklmnopqrstuvw"
    mock_slack = f"https://hooks.{'slack'}.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"

    env_content = f"""# Production configuration
PORT=8080
NODE_ENV=production
APP_NAME="MyEnterpriseApp"
DEBUG=false

# Leaked Database Credentials
DATABASE_URL=postgres://postgres:p@ssword123@db.prod.internal:5432/main_db
REDIS_URL=redis://:supersecretredispass@cache.internal:6379/0

# Leaked Cloud & SaaS Keys
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz
ANTHROPIC_API_KEY=sk-ant-api03-1234567890abcdefghijklmnopqrstuvwxyz1234567890
STRIPE_SECRET_KEY={mock_stripe}

# App & Auth Secrets
JWT_SECRET="super-secret-jwt-signing-key-999!" # jwt signing secret
SESSION_SECRET='cookie-session-encryption-secret'
SLACK_WEBHOOK_URL={mock_slack}
"""
    vault = RequestVault()
    engine = MaskingEngine(vault)
    masked = engine.mask_text(env_content)

    # 1. Verify safe keys are NOT masked
    assert "PORT=8080" in masked
    assert "NODE_ENV=production" in masked
    assert 'APP_NAME="MyEnterpriseApp"' in masked
    assert "DEBUG=false" in masked

    # 2. Verify sensitive credentials were NOT passed through in raw form
    assert "p@ssword123" not in masked
    assert "supersecretredispass" not in masked
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in masked
    assert "sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz" not in masked
    assert "sk-ant-api03-1234567890abcdefghijklmnopqrstuvwxyz1234567890" not in masked
    assert mock_stripe not in masked
    assert "super-secret-jwt-signing-key-999!" not in masked
    assert "cookie-session-encryption-secret" not in masked
    assert "XXXXXXXXXXXXXXXXXXXXXXXX" not in masked

    # 3. Verify tokens exist in masked text and structure is intact
    assert "DATABASE_URL=[SECRET_" in masked
    assert "REDIS_URL=[SECRET_" in masked
    assert "AWS_SECRET_ACCESS_KEY=[SECRET_" in masked
    assert 'JWT_SECRET="[SECRET_' in masked
    assert "SESSION_SECRET='[SECRET_" in masked
    assert "# jwt signing secret" in masked  # comment preserved

    # 4. Verify round-trip restoration restores exact raw secrets
    restored = restore_text(masked, vault)
    assert restored == env_content


def test_devops_private_key_leak_detection():
    """Verify PEM and OpenSSH private key blocks are fully masked."""
    rsa_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0m4Qz2W7U9uYf1234567890abcdefghijklmnopqrstuvwxyz
ABCDEFGHIJKLMOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz==
-----END RSA PRIVATE KEY-----"""

    text = f"Here is my deployer key:\n{rsa_key}\nPlease fix the SSH connection."
    vault = RequestVault()
    engine = MaskingEngine(vault)
    masked = engine.mask_text(text)

    assert "MIIEowIBAAKCAQEA0m4Qz" not in masked
    assert "[SECRET_1]" in masked
    restored = restore_text(masked, vault)
    assert rsa_key in restored


def test_database_connection_strings_in_text():
    """Verify various database connection strings are masked whether pasted alone or
    in errors."""
    uris = [
        "postgresql://appuser:SecretPass123@10.0.0.5:5432/orders",
        "mysql://root:toor1234@db.prod:3306/users",
        "mongodb+srv://admin:clusterpass@cluster0.abcde.mongodb.net/test?retryWrites=true",
        "redis://:authpassword99@redis-cache:6379/0",
    ]
    for uri in uris:
        text = f"Connection failed on {uri} with timeout."
        vault = RequestVault()
        engine = MaskingEngine(vault)
        masked = engine.mask_text(text)
        assert uri not in masked
        assert "[SECRET_1]" in masked
        restored = restore_text(masked, vault)
        assert uri in restored


def test_bearer_token_authorization_header():
    """Verify Bearer token values are masked while keeping the Bearer keyword intact."""
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjoiYWRtaW4ifQ.signature12345"
    text = f"Authorization: Bearer {token}"

    vault = RequestVault()
    engine = MaskingEngine(vault)
    masked = engine.mask_text(text)

    assert "Authorization: Bearer [SECRET_1]" in masked
    restored = restore_text(masked, vault)
    assert restored == text


def test_cloud_provider_tokens():
    """Verify detection across cloud providers: Google, GitLab, HuggingFace, PyPI,
    NPM, SendGrid."""
    pypi_sample = (
        "pypi-AgEIcHlwaS5vcmcCJDEyMzQ1Njc4LWFhYWEtYmJiYi1jY2NjLWRkZGRkZGRkZGRkZAACKD"
    )
    sg_sample = (
        "SG.1234567890abcdefghijkA.1234567890abcdefghijklmnopqrstuvwxyz12345678901"
    )
    samples = [
        ("Google AI", "AIzaSyD-1234567890abcdefghijklmnopqrst"),
        ("GitLab PAT", "glpat-abcdef1234567890_xyz"),
        ("HuggingFace", "hf_abcdefghijklmnopqrstuvwxyz12345678"),
        ("PyPI Token", pypi_sample),
        ("NPM Token", "npm_abcdefghijklmnopqrstuvwxyz123456"),
        ("SendGrid", sg_sample),
    ]

    for label, secret_val in samples:
        text = f"{label} secret key is {secret_val}."
        spans = detect_secrets(text)
        assert len(spans) >= 1, f"Failed to detect {label}: {secret_val}"
        vault = RequestVault()
        engine = MaskingEngine(vault)
        masked = engine.mask_text(text)
        assert secret_val not in masked
        assert "[SECRET_1]" in masked
        assert restore_text(masked, vault) == text


def test_empty_and_trivial_env_keys_not_flagged():
    """Verify empty or template environment keys are not flagged as secrets."""
    config_text = """
VAULT_PROFILE=development
VAULT_AUTH_TOKEN=
UPSTREAM_BASE_URL=https://api.openai.com/v1
UPSTREAM_API_KEY=
GEMMA_BACKEND=off
STRICT_MODE=false
DEMO_MODE=false
"""
    spans = detect_secrets(config_text)
    assert len(spans) == 0, f"Expected 0 spans for empty config, got: {spans}"


def test_connection_string_with_trailing_punctuation():
    """Verify connection strings in natural sentences do not swallow periods or commas."""
    text = "Database is at postgresql://user:pass@host:5432/main_db."
    vault = RequestVault()
    engine = MaskingEngine(vault)
    masked = engine.mask_text(text)
    assert masked == "Database is at [SECRET_1]."
    assert restore_text(masked, vault) == text
