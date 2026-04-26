"""Settings + log configuration for the webhook."""
from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings


SETTINGS: "Settings | None" = None


class LogConfig(BaseModel):
    LOGGER_NAME: str = "webhook"
    LOG_FORMAT: str = "%(levelprefix)s | %(asctime)s | %(message)s"
    LOG_LEVEL: str = "INFO"

    version: int = 1
    disable_existing_loggers: bool = False
    formatters: dict = {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(levelprefix)s | %(asctime)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }
    handlers: dict = {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    }
    loggers: dict = {
        "webhook": {"handlers": ["default"], "level": "INFO"},
    }


class Settings(BaseSettings):
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9997


def load() -> Settings:
    global SETTINGS
    SETTINGS = Settings()
    return SETTINGS
