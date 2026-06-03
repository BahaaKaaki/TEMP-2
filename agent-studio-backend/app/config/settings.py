"""
Application configuration and settings.

Centralized configuration for limits, timeouts, and environment-specific settings.
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import Optional
from config.keyvault import cfg


class AppSettings(BaseSettings):
    """
    Application-wide configuration settings.
    
    Uses Pydantic BaseSettings for automatic environment variable loading.
    Environment variables can override defaults (e.g., MAX_REQUEST_SIZE_MB=20).
    """
    
    # ============================================================================
    # REQUEST LIMITS (Security & Stability)
    # ============================================================================
    
    # Maximum size of HTTP request body (prevents memory exhaustion)
    MAX_REQUEST_SIZE_MB: int = Field(
        default=10,
        description="Maximum request body size in MB (HTTP payloads, JSON)"
    )
    
    # Maximum size of uploaded files
    MAX_FILE_SIZE_MB: int = Field(
        default=50,
        description="Maximum file upload size in MB"
    )
    
    # Maximum length of chat messages
    MAX_MESSAGE_LENGTH: int = Field(
        default=100000,
        description="Maximum characters in a single chat message"
    )
    
    # Maximum number of files per upload batch
    MAX_FILES_PER_UPLOAD: int = Field(
        default=10,
        description="Maximum files that can be uploaded in a single request"
    )
    
    # Maximum size of variables dictionary
    MAX_VARIABLES_SIZE: int = Field(
        default=50000,
        description="Maximum JSON string size for workflow variables"
    )
    
    # ============================================================================
    # KNOWLEDGE BASE & SEARCH SETTINGS
    # ============================================================================
    
    # Vector index configuration
    VECTOR_INDEX_TYPE: str = Field(
        default="vchordrq",
        description="Vector index type: 'vchordrq' (VectorChord) or 'diskann' (Microsoft DiskANN)"
    )
    
    VECTOR_DISTANCE_METRIC: str = Field(
        default="cosine",
        description="Distance metric: 'cosine' (recommended for OpenAI/normalized embeddings) or 'l2' (Euclidean)"
    )
    
    # Default search parameters
    KB_DEFAULT_TOP_K: int = Field(
        default=10,
        description="Default number of search results to return from KB"
    )
    
    KB_MAX_SEARCH_CHARS: int = Field(
        default=8000,
        description="Maximum total characters returned per KB search call. Chunks are added until this budget is exhausted."
    )
    
    KB_MAX_CHUNK_CHARS: int = Field(
        default=2500,
        description="Maximum characters kept per individual chunk. Longer chunks are truncated to this length."
    )
    
    KB_RERANK_MULTIPLIER: int = Field(
        default=2,
        description="Multiplier for initial search when reranking (fetch top_k * multiplier, then rerank to top_k)"
    )
    
    # Reranker model configuration
    KB_RERANKER_MODEL: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Default reranker model for improving search relevance"
    )
    
    # Hybrid search parameters
    KB_HYBRID_SEMANTIC_WEIGHT: float = Field(
        default=0.5,
        description="Weight for semantic search in hybrid mode (0.0-1.0, where 1.0 is pure semantic)"
    )
    
    KB_HYBRID_RRF_K: int = Field(
        default=60,
        description="RRF (Reciprocal Rank Fusion) constant for hybrid search ranking"
    )
    
    # Agentic KB Researcher settings
    KB_RESEARCHER_ENABLED: bool = Field(
        default=True,
        description="Enable the agentic KB researcher (CRAG + query decomposition). When False, falls back to simple single-shot search."
    )
    
    KB_RESEARCHER_MAX_SUB_QUERIES: int = Field(
        default=5,
        description="Maximum number of sub-queries the researcher generates per decomposition"
    )
    
    KB_RESEARCHER_MAX_RETRIES: int = Field(
        default=1,
        description="Maximum reformulation retries per sub-query when grading is AMBIGUOUS"
    )
    
    KB_RESEARCHER_MEMO_MAX_CHARS: int = Field(
        default=12000,
        description="Maximum characters in the final research memo returned to the Main LLM"
    )
    
    KB_RESEARCHER_SCORE_THRESHOLD: float = Field(
        default=0.0,
        description="Minimum relevance score to keep a chunk (0 = no filtering)"
    )
    
    KB_RESEARCHER_MAX_RESULT_CHARS: int = Field(
        default=100000,
        description="Maximum total characters of chunk text in the formatted researcher output"
    )
    
    KB_RESEARCHER_GRADER_MODEL: str = Field(
        default="bedrock.anthropic.claude-haiku-4-5",
        description="Lightweight LLM used for query decomposition, relevance grading, and synthesis inside the researcher"
    )
    
    KB_RESEARCHER_GRADER_PROVIDER: str = Field(
        default="bedrock",
        description="LLM provider for the researcher's internal grader model"
    )
    
    # Text truncation limits
    TEXT_PREVIEW_LENGTH: int = Field(
        default=100,
        description="Default preview length for text snippets (in characters)"
    )
    
    FILE_CONTENT_MAX_LENGTH: int = Field(
        default=10000,
        description="Maximum length for file content before truncation (in characters)"
    )
    
    TOOL_RESULT_MAX_LENGTH: int = Field(
        default=5000,
        description="Maximum length for tool result before truncation (in characters)"
    )
    
    # ============================================================================
    # IMAGE OCR / VISION SETTINGS
    # ============================================================================
    # Used when a user uploads an image (png/jpg/...). The image bytes are
    # base64-encoded and sent to a vision-capable LLM through the GenAI
    # proxy. The LLM transcribes any visible text and writes a short visual
    # description, which is then stored in chat_file.extracted_text just
    # like text from any other parsed document.
    
    OCR_VISION_ENABLED: bool = Field(
        default=True,
        description="When False, image uploads are stored but no OCR is attempted (extracted_text stays empty)."
    )
    
    OCR_VISION_PROVIDER: str = Field(
        default="google",
        description="LLM provider for image OCR. Routed through the GenAI proxy (google -> vertex_ai prefix)."
    )
    
    OCR_VISION_MODEL: str = Field(
        default="vertex_ai.gemini-3.1-flash-lite-preview",
        description="Vision-capable model used for image OCR. Defaults to Gemini Flash Lite for cost/latency."
    )
    
    OCR_VISION_TIMEOUT: int = Field(
        default=60,
        description="Timeout (seconds) for the vision OCR call."
    )
    
    OCR_VISION_MAX_BYTES: int = Field(
        default=20 * 1024 * 1024,
        description="Maximum image size (bytes) accepted by the OCR pipeline. Larger images are rejected with a parsing error."
    )
    
    OCR_VISION_MAX_OUTPUT_TOKENS: int = Field(
        default=4096,
        description="Maximum tokens of OCR output produced by the vision model per image."
    )
    
    # ============================================================================
    # AUTHENTICATION & SECURITY SETTINGS
    # ============================================================================
    
    # JWT configuration
    JWT_SECRET_KEY: Optional[str] = Field(
        default=None,
        description="Secret key for JWT token signing (MUST be set via env or keyvault)"
    )
    
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="Algorithm for JWT token encoding (locked to HS256)"
    )
    
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,
        description="Access token expiration time in minutes"
    )
    
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        description="Refresh token expiration time in days"
    )
    
    # Password requirements
    PASSWORD_MIN_LENGTH: int = Field(
        default=8,
        description="Minimum password length"
    )
    
    # Cookie and CORS settings
    CORS_ALLOWED_ORIGINS: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins"
    )
    
    COOKIE_DOMAIN: Optional[str] = Field(
        default=None,
        description="Domain for auth cookies (None = current domain only)"
    )
    
    COOKIE_SECURE: bool = Field(
        default=False,
        description="Set Secure flag on auth cookies (True in production behind HTTPS)"
    )
    
    OAUTH_CODE_TTL_SECONDS: int = Field(
        default=60,
        description="TTL for one-time OAuth authorization codes stored in Redis"
    )
    
    FORWARDED_ALLOW_IPS: str = Field(
        default="127.0.0.1",
        description="Comma-separated trusted proxy IPs for X-Forwarded-* headers ('*' to trust all)"
    )
    
    # Rate limiting for auth endpoints
    RATE_LIMIT_AUTH_PER_MINUTE: int = Field(
        default=5,
        description="Maximum login/register attempts per minute per IP"
    )
    
    RATE_LIMIT_REFRESH_PER_MINUTE: int = Field(
        default=10,
        description="Maximum token refresh requests per minute per IP"
    )
    
    # OAuth/External provider configuration
    MICROSOFT_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Microsoft Entra ID application (client) ID"
    )
    
    MICROSOFT_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="Microsoft Entra ID client secret"
    )
    
    MICROSOFT_TENANT_ID: Optional[str] = Field(
        default=None,
        description="Microsoft Entra ID tenant ID"
    )

    MS_TOKEN_ENCRYPTION_KEY: Optional[str] = Field(
        default=None,
        description=(
            "Fernet key used to encrypt each user's Microsoft OAuth refresh "
            "token at rest in the ms_oauth_token table. Generate with: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\". "
            "Losing this key forces every user to re-authenticate via SSO."
        ),
    )

    FRONTEND_URL: str = Field(
        default="http://localhost:5173",
        description="Frontend application URL (used for OAuth redirect after authentication)"
    )
    
    AUTHENTICATION_REDIRECTION: str = Field(
        default="",
        description=(
            "Public-facing base URL used to build the OAuth redirect URI "
            "registered in Microsoft Entra ID "
            "(e.g. https://gateway.example.com or the frontend URL). "
            "Leave empty for local dev — the URL will be auto-detected "
            "from X-Forwarded-* request headers."
        ),
    )
    
    # ============================================================================
    # EMBEDDING SETTINGS
    # ============================================================================
    
    # Embedding dimensions for different models
    EMBEDDING_DIM_ADA_002: int = Field(
        default=1536,
        description="Embedding dimension for text-embedding-ada-002"
    )
    
    EMBEDDING_DIM_SMALL: int = Field(
        default=1536,
        description="Embedding dimension for text-embedding-3-small"
    )
    
    EMBEDDING_DIM_LARGE: int = Field(
        default=3072,
        description="Embedding dimension for text-embedding-3-large"
    )
    
    # Default dimension if model not found
    EMBEDDING_DIM_DEFAULT: int = Field(
        default=1536,
        description="Default embedding dimension for unknown models"
    )
    
    # Batch size for embedding generation
    EMBEDDING_BATCH_SIZE: int = Field(
        default=512,
        description="Number of texts to embed in a single batch"
    )
    
    # ============================================================================
    # APPLICATION SETTINGS
    # ============================================================================
    
    APP_NAME: str = Field(
        default="Agent Builder API",
        description="Application name"
    )
    
    APP_VERSION: str = Field(
        default="1.0.0",
        description="Application version"
    )
    
    ENVIRONMENT: str = Field(
        default="development",
        description="Environment: development, staging, production"
    )

    EDWIN_API_URL: Optional[str] = Field(
        default=None,
        description="Edwin API base URL for PowerPoint Generator handoffs (POST /api/handoffs)",
    )
    
    # Server configuration
    HOST: str = Field(
        default="0.0.0.0",
        description="Server host address"
    )
    
    PORT: int = Field(
        default=8000,
        description="Server port"
    )
    
    # ============================================================================
    # LOGGING SETTINGS
    # ============================================================================
    
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )
    
    LOG_MAX_BYTES: int = Field(
        default=10485760,  # 10MB
        description="Maximum size of log file before rotation (bytes)"
    )
    
    LOG_BACKUP_COUNT: int = Field(
        default=5,
        description="Number of rotated log files to keep"
    )
    
    # ============================================================================
    # DATABASE SETTINGS
    # ============================================================================
    
    DB_POOL_MIN_SIZE: int = Field(
        default=1,
        description="Minimum database connection pool size"
    )
    
    DB_POOL_MAX_SIZE: int = Field(
        default=15,
        description="Maximum database connection pool size"
    )
    
    DB_TIMEOUT: int = Field(
        default=30,
        description="Database query timeout in seconds"
    )
    
    # ============================================================================
    # REDIS SETTINGS
    # ============================================================================
    
    REDIS_TIMEOUT: int = Field(
        default=5,
        description="Redis operation timeout in seconds"
    )

    TRACE_STREAM_TTL_SECONDS: int = Field(
        default=86400,
        description="Redis TTL for per-execution trace streams"
    )

    TRACE_STREAM_MAXLEN: int = Field(
        default=3000,
        description="Approximate maximum Redis Stream entries kept per execution trace"
    )
    
    # ============================================================================
    # FILE STORAGE SETTINGS
    # ============================================================================
    
    UPLOAD_DIR: str = Field(
        default="./uploads",
        description="Local directory for file uploads"
    )
    
    STORAGE_TIMEOUT: int = Field(
        default=30,
        description="Cloud storage operation timeout in seconds"
    )
    
    # Azure Storage configuration
    AZURE_STORAGE_ACCOUNT_NAME: Optional[str] = Field(
        default=None,
        description="Azure Storage account name (required for Managed Identity)"
    )
    
    AZURE_STORAGE_USE_MANAGED_IDENTITY: bool = Field(
        default=False,
        description="Use Azure AD Managed Identity for storage authentication"
    )
    
    # ============================================================================
    # WORKFLOW SETTINGS
    # ============================================================================
    
    MAX_WORKFLOW_ITERATIONS: int = Field(
        default=10,
        description="Maximum iterations for agent tool loops"
    )
    
    WORKFLOW_TIMEOUT: int = Field(
        default=300,
        description="Maximum workflow execution time in seconds"
    )
    
    # ============================================================================
    # KNOWLEDGE BASE SETTINGS
    # ============================================================================
    
    KB_CHUNK_SIZE: int = Field(
        default=1000,
        description="Default text chunk size for knowledge base"
    )
    
    KB_CHUNK_OVERLAP: int = Field(
        default=200,
        description="Overlap between consecutive chunks"
    )
    
    KB_SEARCH_TOP_K: int = Field(
        default=5,
        description="Default number of search results to return"
    )
    
    KB_MAX_CHUNKS_PER_DOCUMENT: int = Field(
        default=10000,
        description="Maximum chunks per document (prevents abuse)"
    )
    
    # ============================================================================
    # RATE LIMITING SETTINGS
    # ============================================================================
    
    # Global rate limits (per IP address)
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Enable rate limiting (disable for development)"
    )
    
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=100,
        description="Maximum requests per minute per IP (global limit)"
    )
    
    RATE_LIMIT_PER_HOUR: int = Field(
        default=1000,
        description="Maximum requests per hour per IP (global limit)"
    )
    
    # Endpoint-specific rate limits
    RATE_LIMIT_CHAT_PER_MINUTE: int = Field(
        default=10,
        description="Maximum chat messages per minute per IP"
    )
    
    RATE_LIMIT_FILE_UPLOAD_PER_MINUTE: int = Field(
        default=5,
        description="Maximum file uploads per minute per IP"
    )
    
    RATE_LIMIT_KB_UPLOAD_PER_MINUTE: int = Field(
        default=3,
        description="Maximum KB document uploads per minute per IP"
    )
    
    RATE_LIMIT_WORKFLOW_PER_MINUTE: int = Field(
        default=20,
        description="Maximum workflow executions per minute per IP"
    )
    
    # Rate limit storage backend
    RATE_LIMIT_STORAGE_URL: Optional[str] = Field(
        default=None,
        description="Redis URL for rate limit storage (defaults to memory if not set)"
    )
    
    # ============================================================================
    # WORKER SETTINGS
    # ============================================================================
    
    WORKER_COUNT: Optional[int] = Field(
        default=None,
        description="Number of worker processes (None = auto-calculate from CPU cores)"
    )
    
    @model_validator(mode="after")
    def _fill_keyvault_secrets(self):
        """Backfill secrets from the central config when not found in env."""
        if not self.MICROSOFT_CLIENT_SECRET:
            self.MICROSOFT_CLIENT_SECRET = cfg.MICROSOFT_CLIENT_SECRET
        kv_jwt = getattr(cfg, "JWT_SECRET_KEY", None)
        if kv_jwt and not self.JWT_SECRET_KEY:
            self.JWT_SECRET_KEY = kv_jwt
        return self

    @model_validator(mode="after")
    def _validate_security_settings(self):
        """Enforce security constraints that must hold in non-dev environments."""
        env = self.ENVIRONMENT.lower()
        if env in ("production", "staging"):
            if not self.JWT_SECRET_KEY:
                raise ValueError(
                    "JWT_SECRET_KEY must be set via environment variable or keyvault "
                    "when ENVIRONMENT is production or staging"
                )
        if self.JWT_ALGORITHM != "HS256":
            raise ValueError("JWT_ALGORITHM must be HS256")
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Global settings instance
settings = AppSettings()


def get_settings() -> AppSettings:
    """
    Get application settings instance.
    
    Returns:
        AppSettings: Singleton settings instance
    """
    return settings


def get_max_request_size_bytes() -> int:
    """
    Get maximum request size in bytes.
    
    Returns:
        int: Maximum request size in bytes
    """
    return settings.MAX_REQUEST_SIZE_MB * 1024 * 1024


def get_max_file_size_bytes() -> int:
    """
    Get maximum file size in bytes.
    
    Returns:
        int: Maximum file size in bytes
    """
    return settings.MAX_FILE_SIZE_MB * 1024 * 1024


# Environment-specific configurations
def is_production() -> bool:
    """Check if running in production environment."""
    return settings.ENVIRONMENT.lower() == "production"


def is_development() -> bool:
    """Check if running in development environment."""
    return settings.ENVIRONMENT.lower() == "development"


def is_staging() -> bool:
    """Check if running in staging environment."""
    return settings.ENVIRONMENT.lower() == "staging"
