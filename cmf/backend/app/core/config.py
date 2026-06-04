"""
Application configuration settings.
Loads environment variables from .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database configuration
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/qms_db"
    
    # Blob storage configuration
    BLOB_STORAGE_PATH: str = "./blob_data"
    
    # API configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "QMS FastAPI Backend"
    VERSION: str = "1.0.0"
    
    # PaddleX configuration
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK: Optional[str] = "True"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()

