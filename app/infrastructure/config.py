"""Application configuration using nested Pydantic BaseSettings."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """HTTP API server configuration."""

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])


class QualityGateSettings(BaseSettings):
    """Image quality gate thresholds."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    min_blur_score: float = Field(
        default=100.0,
        validation_alias=AliasChoices("BLUR_THRESHOLD", "MIN_BLUR_SCORE"),
    )
    min_brightness: float = 40.0
    max_brightness: float = 220.0
    max_image_size_mb: int = 10
    max_image_dim: int = Field(default=1600, gt=0)
    glare_pixel_ratio_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    strict_quality_gate: bool = True
    apply_clahe: bool = True


class OcrSettings(BaseSettings):
    """Local OCR engine configuration."""

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = True
    lang: str = "id"
    use_angle_cls: bool = True
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    model_dir: str | None = None


class LlmSettings(BaseSettings):
    """OpenAI-compatible / Ollama LLM configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "qwen2.5vl:7b"
    timeout_seconds: float = 15.0
    max_retries: int = 2
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class PlaygroundSettings(BaseSettings):
    """Interactive playground UI configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enable_playground: bool = False


class Settings(BaseSettings):
    """Root application settings composed of domain-specific sub-models."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = "development"
    service_name: str = "miru-id"
    version: str = Field(
        default="0.1.0",
        validation_alias=AliasChoices("APP_VERSION", "VERSION"),
    )
    log_level: str = "INFO"

    api: ApiSettings = Field(default_factory=ApiSettings)
    quality_gate: QualityGateSettings = Field(default_factory=QualityGateSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    playground: PlaygroundSettings = Field(default_factory=PlaygroundSettings)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
