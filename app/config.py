import os
from functools import lru_cache
from typing import Optional, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        case_sensitive=False,
        protected_namespaces=(),
    )

    project_id: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", "")
    )
    location: str = Field(default="us-central1")
    model_id: str = Field(default="gemini-2.0-flash-001")
    token_secret: str = Field(default="dev-secret-change-me")
    token_ttl_minutes: int = Field(default=60)
    default_request_limit: int = Field(default=15_000)
    default_concurrency_cap: int = Field(default=1)
    allow_registration_endpoint: bool = Field(default=True)
    admin_emails: List[str] = Field(default_factory=lambda: ["btc.esmt.workshop@gmail.com"])
    admin_ui_user: str = Field(default="alxefremov")
    admin_ui_password: str = Field(default="adminadmin")

    @field_validator("project_id")
    @classmethod
    def _require_project(cls, v: str) -> str:
        if not v:
            raise ValueError(
                "project_id is empty. Set GOOGLE_CLOUD_PROJECT or APP_PROJECT_ID."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]
