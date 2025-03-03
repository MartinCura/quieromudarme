"""Runtime configuration for the chatbot module."""

from enum import StrEnum
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict

from quieromudarme.chatbot.base import TelegramID

MARTIN_TG_ID: Final = 195525674


class Env(StrEnum):
    """Environment names."""

    DEV = "dev"
    PROD = "prod"


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Env = Env.DEV

    # Chatbot settings
    tg_app_api_id: str
    tg_app_api_hash: str
    tg_bot_token: str
    admin_tg_user_id: TelegramID = MARTIN_TG_ID

    # Providers settings
    mercadopago_access_token: str

    @property
    def tg_bot_id(self) -> TelegramID:
        return int(self.tg_bot_token.split(":")[0])


cfg = _Settings()
