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

    ai_provider: str = "mock"
    ai_timeout_seconds: int = 30
    ai_max_retries: int = 2
    ai_schema_repair_retries: int = 1
    ai_temperature: float = 0.1
    agent_max_model_turns: int = 3
    agent_max_tool_rounds: int = 2
    agent_max_tool_calls_per_round: int = 3
    agent_max_total_tool_calls: int = 6
    agent_loop_timeout_seconds: int = 25
    conversation_summary_trigger_tokens: int = 3000
    conversation_summary_keep_tokens: int = 1500
    conversation_summary_max_chars: int = 2000
    summary_llm_enabled: bool = True
    summary_llm_model: str = "qwen-turbo"
    conversation_summary_worker_limit: int = 10
    conversation_summary_worker_interval_seconds: float = 5.0
    conversation_summary_running_timeout_seconds: int = 600
    asr_provider: str = "mock"
    vision_provider: str = "mock"
    dashscope_asr_endpoint: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
    )
    dashscope_task_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/tasks"
    dashscope_asr_model: str = "paraformer-v2"
    dashscope_asr_language_hints: str = "zh,en"
    dashscope_asr_poll_interval_seconds: float = 0.5
    dashscope_asr_max_wait_seconds: int = 20
    bailian_api_key: str = ""
    dashscope_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model: str = "qwen-plus"
    media_upload_dir: str = "./var/uploads"
    media_public_base_url: str = "http://127.0.0.1:8000"
    media_max_upload_bytes: int = 10 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
