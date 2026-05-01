import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.sms.provider import AliyunSmsProvider, MockSmsProvider


def test_mock_sms_provider_accepts_configured_code() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        sms_mock_code="654321",
    )
    provider = MockSmsProvider(settings)

    send_result = provider.send_code("13800138000", "86")
    check_result = provider.check_code("13800138000", "86", "654321")

    assert send_result.success is True
    assert check_result.success is True
    assert check_result.verify_result == "PASS"


def test_mock_sms_provider_rejects_wrong_code() -> None:
    settings = Settings(jwt_secret_key="test-secret-key-with-enough-length")
    provider = MockSmsProvider(settings)

    check_result = provider.check_code("13800138000", "86", "000000")

    assert check_result.success is False
    assert check_result.verify_result == "FAIL"


def test_aliyun_sms_provider_requires_credentials() -> None:
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        sms_provider="aliyun",
        aliyun_access_key_id="",
        aliyun_access_key_secret="",
        aliyun_sms_sign_name="",
        aliyun_sms_template_code="",
    )
    provider = AliyunSmsProvider(settings)

    with pytest.raises(AppError) as exc_info:
        provider.send_code("13800138000", "86")

    assert exc_info.value.code == "INTERNAL_ERROR"
    assert "ALIYUN_ACCESS_KEY_ID" in exc_info.value.details["missing"]
