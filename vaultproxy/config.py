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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
