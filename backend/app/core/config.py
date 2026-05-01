from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LetMeFit Backend"
    app_version: str = "0.1.0"
    environment: str = "local"
    api_prefix: str = "/v1"

    database_url: str = "mysql+pymysql://letmefit:letmefit@localhost:3306/letmefit"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = Field(default="change-me-in-local-dev-only", min_length=16)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 30

    sms_provider: str = "mock"
    sms_mock_code: str = "123456"
    sms_country_code: str = "86"
    sms_send_cooldown_seconds: int = 60
    sms_expires_in_seconds: int = 300
    sms_max_failed_attempts: int = 5
    sms_failed_lock_seconds: int = 600

    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_dypns_endpoint: str = "dypnsapi.aliyuncs.com"
    aliyun_sms_scheme_name: str = ""
    aliyun_sms_sign_name: str = ""
    aliyun_sms_template_code: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
