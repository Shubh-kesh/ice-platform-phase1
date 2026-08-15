"""
Central configuration for the ICE backend.
All values are read from environment variables (see .env.example).
Never hardcode secrets here — this file is committed to git.
"""
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    PROJECT_NAME: str = "Intelligent Construction Engine"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "local"  # local | staging | production

    # Security
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Window (seconds) in which re-presenting an already-rotated token is treated
    # as a benign concurrent-race (two tabs refreshing at once) rather than theft.
    # Beyond this window reuse revokes the whole rotation family.
    REFRESH_TOKEN_REUSE_GRACE_SECONDS: int = 10
    ALGORITHM: str = "HS256"

    # CORS — list of allowed frontend origins
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:5173"]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        return v

    # Database
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Used by Alembic, which doesn't support async drivers directly."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # Google OAuth (M11) — empty values disable the Google sign-in surfaces.
    # All values come from env (backend/.env, never committed).
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:5173/google/callback"
    # Optional workspace-domain lock: when set, only Google accounts whose
    # `hd` matches are accepted (ID token `hd` claim).
    GOOGLE_HOSTED_DOMAIN: str = ""
    # Authorization-code `state` freshness window in seconds.
    GOOGLE_AUTH_STATE_MAX_AGE_SECONDS: int = 600

    @property
    def GOOGLE_AUTH_ENABLED(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    # GCP (only required in production)
    GCP_PROJECT_ID: str = ""
    GCS_BUCKET_NAME: str = ""

    # ICE Copilot (Phase AI-1) — provider-agnostic via the LangChain model
    # abstraction (init_chat_model). Provider/model/API keys come from env;
    # secrets are never committed. Default provider is OpenAI but nothing in
    # the AI module depends on it — swapping ICE_AI_PROVIDER / ICE_AI_MODEL
    # (and setting the matching key) is enough to move providers. Fallback /
    # retry middleware is an AI-4 concern.
    ICE_AI_ENABLED: bool = False
    ICE_AI_PROVIDER: str = "openai"  # openai | anthropic | groq | openrouter
    ICE_AI_MODEL: str = "gpt-5-mini"
    # Generic fallback API key; a provider-specific key takes precedence.
    ICE_AI_API_KEY: str = ""
    ICE_AI_OPENAI_API_KEY: str = ""
    ICE_AI_ANTHROPIC_API_KEY: str = ""
    ICE_AI_GROQ_API_KEY: str = ""
    ICE_AI_OPENROUTER_API_KEY: str = ""
    # Optional custom endpoint for OpenAI-compatible providers (a proxy such as
    # opencode, or OpenRouter's api). Empty -> the provider's default endpoint.
    ICE_AI_BASE_URL: str = ""
    ICE_AI_TEMPERATURE: float = 0.0
    ICE_AI_MAX_TOOL_RESULT_CHARS: int = 4000
    ICE_AI_DEBUG: bool = False


settings = Settings()
