from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    UPSTREAM_BASE_URL: str = "http://localhost:8001"
    UPSTREAM_API_KEY: str = ""
    GEMMA_BACKEND: str = "off"
    OLLAMA_URL: str = "http://localhost:11434"
    GEMMA_MODEL: str = "gemma4:e2b"
    GEMINI_API_KEY: str = ""
    GEMMA_TIMEOUT_SECONDS: float = 8.0
    STRICT_MODE: bool = False
    DEMO_MODE: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
