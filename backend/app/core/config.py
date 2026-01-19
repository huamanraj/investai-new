"""
Application configuration loaded from environment variables
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from pathlib import Path

# Get the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings"""
    
    # App
    APP_NAME: str = "InvestAI"
    ENV: str = "development"
    DEBUG: bool = True
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database
    DATABASE_URL: str = ""
    
    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OPENAI_CHAT_MODEL: str = "gpt-4.1"
    
    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    
    # Playwright
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_TIMEOUT: int = 30000
    
    # PDF / Ingestion
    CHUNK_SIZE: int = 400
    CHUNK_OVERLAP: int = 80
    MAX_CHUNKS_PER_PAGE: int = 10
    
    # RAG / Search
    MAX_SIMILARITY_RESULTS: int = 25
    MAX_PROJECTS_PER_CHAT: int = 5
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    # LlamaCloud (LlamaExtract)
    LLAMA_CLOUD_API_KEY: str = ""
    
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
