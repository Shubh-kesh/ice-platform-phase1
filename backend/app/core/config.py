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
    # W7.1 conversation memory.
    # ICE_AI_MEMORY_MODE: none | saver | summarize | context_edit
    #   none         -> stateless (AI-1 behavior), no checkpointer
    #   saver        -> InMemorySaver + thread_id multi-turn memory
    #   summarize    -> saver + SummarizationMiddleware (experiment)
    #   context_edit -> saver + ContextEditingMiddleware/ClearToolUsesEdit (experiment)
    # InMemorySaver is PROCESS-LOCAL: memory disappears on restart and is not
    # shared across backend workers (documented W7.1 limitation — no Redis/DB).
    ICE_AI_MEMORY_MODE: str = "saver"
    ICE_AI_SUMMARIZE_TRIGGER_KIND: str = "messages"
    ICE_AI_SUMMARIZE_TRIGGER_VALUE: int = 40
    ICE_AI_SUMMARIZE_KEEP: int = 20
    ICE_AI_CONTEXT_EDIT_TRIGGER: int = 5000  # approx tokens before clearing old tool uses
    ICE_AI_CONTEXT_EDIT_KEEP: int = 3  # recent tool uses kept
    # W7.2 external web search (Tavily API via a direct async httpx wrapper —
    # no SDK dependency). Default OFF; the key is a provider secret.
    ICE_AI_WEB_SEARCH_ENABLED: bool = False
    ICE_AI_TAVILY_API_KEY: str = ""
    ICE_AI_WEB_SEARCH_MAX_RESULTS: int = 5
    ICE_AI_WEB_SEARCH_TIMEOUT_SECONDS: float = 10.0
    ICE_AI_WEB_SEARCH_MAX_RESULT_CHARS: int = 2000
    # ToolRetryMiddleware (external only) — retry transient web failures only.
    ICE_AI_WEB_SEARCH_RETRIES: int = 2  # max retries after the initial attempt
    ICE_AI_WEB_SEARCH_RETRY_INITIAL_DELAY: float = 0.2
    ICE_AI_WEB_SEARCH_RETRY_BACKOFF: float = 2.0
    # W7.3 middleware/resilience (product-safe defaults; selectors off).
    # Model call limit — bounds runaway agent loops (normal runs are small).
    ICE_AI_MODEL_RUN_LIMIT: int = 8
    ICE_AI_MODEL_THREAD_LIMIT: int = 0  # 0 = unset (no thread-level cap)
    ICE_AI_MODEL_LIMIT_EXIT: str = "end"  # end | error
    # Tool call limit — global + a tight per-tool cap on web_search.
    ICE_AI_TOOL_RUN_LIMIT: int = 15
    ICE_AI_TOOL_THREAD_LIMIT: int = 0
    ICE_AI_WEB_TOOL_RUN_LIMIT: int = 3
    # Model retry — transient same-provider failures only.
    ICE_AI_MODEL_RETRY_MAX: int = 1
    ICE_AI_MODEL_RETRY_INITIAL_DELAY: float = 0.2
    ICE_AI_MODEL_RETRY_BACKOFF: float = 2.0
    # Model fallback — server-side ordered failover (optional).
    ICE_AI_FALLBACK_PROVIDER: str = ""
    ICE_AI_FALLBACK_MODEL: str = ""
    # PII — email/phone redaction is a PRODUCT default (input); custom Aadhaar/
    # PAN detectors are a LEARNING exercise.
    ICE_AI_PII_ENABLED: bool = True
    ICE_AI_PII_STRATEGY: str = "redact"  # redact | mask | block | hash
    ICE_AI_PII_CUSTOM_ENABLED: bool = False
    # TodoList planning (optional; adds a read-only write_todos planning tool).
    ICE_AI_TODO_ENABLED: bool = False
    # LLM tool selector — measurement-gated; OFF by default.
    ICE_AI_TOOL_SELECTOR_ENABLED: bool = False
    ICE_AI_TOOL_SELECTOR_MAX_TOOLS: int = 6
    ICE_AI_TOOL_SELECTOR_ALWAYS_INCLUDE: str = "list_projects,get_project"
    ICE_AI_TOOL_SELECTOR_PROVIDER: str = ""
    ICE_AI_TOOL_SELECTOR_MODEL: str = ""

    # W7.4 — controlled mutations with HumanInTheLoop. OFF by default (the AI
    # stays read-only); enabling turns on the two low-risk mutating tools
    # (create_task, create_daily_site_log), each guarded by an HITL interrupt
    # that requires an explicit human decision via POST /assistant/resume.
    ICE_AI_MUTATIONS_ENABLED: bool = False
    # The mutating tools force the checkpointer-backed "saver" thread mode
    # when this is true (HITL resume needs a user-namespaced thread).
    ICE_AI_HITL_MEMORY_MODE: str = "saver"


settings = Settings()
