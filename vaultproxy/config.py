from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    UPSTREAM_BASE_URL: str = "http://localhost:8001"
    UPSTREAM_API_KEY: str = ""

    GEMMA_BACKEND: str = "auto"
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

    PROFILE: str = "development"
    MASK_SCOPE: str = ""
    NON_TEXT_POLICY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("PROFILE")
    @classmethod
    def validate_profile(cls, v: str) -> str:
        v_lower = v.lower()
        if v_lower not in {"development", "production"}:
            raise ValueError("PROFILE must be 'development' or 'production'")
        return v_lower

    @field_validator("MASK_SCOPE")
    @classmethod
    def validate_mask_scope(cls, v: str) -> str:
        if not v:
            return ""
        v_lower = v.lower()
        if v_lower not in {"messages", "deep"}:
            raise ValueError("MASK_SCOPE must be 'messages' or 'deep'")
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
    def effective_mask_scope(self) -> str:
        if self.MASK_SCOPE:
            return self.MASK_SCOPE.lower()
        return "deep" if self.PROFILE.lower() == "production" else "messages"

    @property
    def effective_non_text_policy(self) -> str:
        if self.NON_TEXT_POLICY:
            return self.NON_TEXT_POLICY.lower()
        return "block" if self.PROFILE.lower() == "production" else "allow"

    @field_validator("GEMMA_BACKEND")
    @classmethod
    def validate_gemma_backend(cls, v: str) -> str:
        valid_backends = {"off", "ollama", "gemini", "auto"}
        v_lower = v.lower()
        if v_lower not in valid_backends:
            raise ValueError(
                f"Invalid GEMMA_BACKEND '{v}'. Must be one of {valid_backends}"
            )
        return v_lower

    @field_validator("GEMMA_MODEL")
    @classmethod
    def validate_gemma_model(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GEMMA_MODEL cannot be empty.")
        return v.strip()


settings = Settings()

