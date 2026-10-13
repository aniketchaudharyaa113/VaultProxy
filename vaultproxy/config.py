import os
import sys

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    UPSTREAM_BASE_URL: str = "http://localhost:8001"
    UPSTREAM_API_KEY: str = ""

    GEMMA_BACKEND: str = "off"
    OLLAMA_URL: str = "http://localhost:11434"
    GEMMA_MODEL: str = "gemma4:e2b"
    GEMMA_AUTODISCOVER: bool = False
    GEMINI_API_KEY: str = ""
    GEMMA_TIMEOUT_SECONDS: float = 8.0
    GEMMA_QUEUE_TIMEOUT_SECONDS: float = 2.0
    GEMMA_CONCURRENCY_LIMIT: int = 4
    GEMMA_CIRCUIT_BREAKER_FAILURES: int = 3
    GEMMA_CIRCUIT_BREAKER_COOLDOWN_SECONDS: float = 30.0
    GEMMA_KEEP_ALIVE: str = "5m"
    GEMMA_TEMPERATURE: float = 0.0
    GEMMA_MAX_TOKENS: int = 512

    STRICT_MODE: bool = False
    DEMO_MODE: bool = False

    VAULT_PROFILE: str = "development"
    NON_TEXT_POLICY: str = ""

    # Phase 5: Production safety settings
    VAULT_AUTH_TOKEN: str = ""  # Client auth token for production access
    MAX_BODY_BYTES: int = 10485760  # 10MB max request body size limit
    REQUEST_TIMEOUT_SECONDS: float = 60.0  # Max total request execution timeout in seconds
    MAX_CONCURRENT_REQUESTS: int = 50  # Max concurrent in-flight requests before HTTP 429

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("VAULT_PROFILE")
    @classmethod
    def validate_profile(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in {"development", "production"}:
            raise ValueError("VAULT_PROFILE must be 'development' or 'production'")
        return v_lower

    @field_validator("NON_TEXT_POLICY")
    @classmethod
    def validate_non_text_policy(cls, v: str) -> str:
        if not v:
            return ""
        v_lower = v.lower()
        if v_lower not in {"allow", "block"}:
            raise ValueError("NON_TEXT_POLICY must be 'allow' or 'block'")
        return v_lower

    @property
    def effective_non_text_policy(self) -> str:
        if self.NON_TEXT_POLICY:
            return self.NON_TEXT_POLICY.lower()
        return "block" if self.VAULT_PROFILE.lower() == "production" else "allow"

    @field_validator("GEMMA_BACKEND")
    @classmethod
    def validate_gemma_backend(cls, v: str) -> str:
        valid_backends = {"off", "ollama", "gemini"}
        v_lower = v.lower()
        if v_lower not in valid_backends:
            allowed = ", ".join(sorted(valid_backends))
            raise ValueError(
                f"Invalid GEMMA_BACKEND '{v}'. Allowed values are: {allowed}."
            )
        return v_lower

    @field_validator("GEMMA_MODEL")
    @classmethod
    def validate_gemma_model(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GEMMA_MODEL cannot be empty.")
        return v.strip()

    @model_validator(mode="after")
    def check_production_constraints(self) -> "Settings":
        """Validate startup production rules."""
        if self.VAULT_PROFILE.lower() == "production":
            if self.DEMO_MODE:
                raise ValueError("DEMO_MODE=true is refused when VAULT_PROFILE=production.")
            if not self.VAULT_AUTH_TOKEN or len(self.VAULT_AUTH_TOKEN) < 24:
                raise ValueError(
                    "VAULT_AUTH_TOKEN is required in production profile and must be at least 24 characters long."
                )
        return self


try:
    settings = Settings()
except Exception as exc:
    err_str = str(exc)
    if "Invalid GEMMA_BACKEND" in err_str:
        backend_val = os.getenv("GEMMA_BACKEND", "")
        sys.stderr.write(
            f"Configuration error: Invalid GEMMA_BACKEND '{backend_val}'. Allowed values are: off, ollama, gemini.\n"
        )
        sys.exit(1)
    if "VAULT_AUTH_TOKEN" in err_str:
        sys.stderr.write(
            "Configuration error: VAULT_AUTH_TOKEN is required in production profile and must be at least 24 characters long.\n"
        )
        sys.exit(1)
    if "DEMO_MODE=true is refused" in err_str:
        sys.stderr.write(
            "Configuration error: DEMO_MODE=true is refused when VAULT_PROFILE=production.\n"
        )
        sys.exit(1)
    sys.stderr.write(f"Configuration error: {err_str}\n")
    sys.exit(1)
