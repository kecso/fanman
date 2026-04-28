"""Environment-backed settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    sysfs_prefix: str = Field(default="/host-sys", validation_alias="SYSFS_PREFIX")
    proc_prefix: str = Field(default="/host-proc", validation_alias="PROC_PREFIX")
    poll_interval: int = Field(default=5, ge=1, validation_alias="POLL_INTERVAL")
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    config_path: str = Field(default="/app/config/fan_curves.json", validation_alias="CONFIG_PATH")
    web_port: int = Field(default=8080, ge=1, le=65535, validation_alias="WEB_PORT")
    failsafe_temp: float = Field(default=85.0, validation_alias="FAILSAFE_TEMP")
    graceful_shutdown_mode: int = Field(default=2, ge=0, le=2, validation_alias="GRACEFUL_SHUTDOWN_MODE")
    max_history_minutes: int = Field(default=60, ge=1, validation_alias="MAX_HISTORY_MINUTES")


@lru_cache
def get_settings() -> Settings:
    return Settings()
