import pytest
from alibabacloud_tea_openapi.exceptions import ClientException

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


class FakeAliyunClient:
    def send_sms_verify_code(self, request):
        raise ClientException(
            status_code=403,
            code="Forbidden.NoPermission",
            message="You are not authorized to perform this action.",
            request_id="req_aliyun",
        )

    def check_sms_verify_code(self, request):
        raise ClientException(
            status_code=403,
            code="Forbidden.NoPermission",
            message="You are not authorized to perform this action.",
            request_id="req_aliyun",
        )


def test_aliyun_sms_provider_returns_structured_send_error() -> None:
    provider = AliyunSmsProvider(
        Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            aliyun_access_key_id="ak",
            aliyun_access_key_secret="secret",
            aliyun_sms_sign_name="sign",
            aliyun_sms_template_code="template",
        )
    )
    provider._client = FakeAliyunClient()

    result = provider.send_code("13800138000", "86")

    assert result.success is False
    assert result.result_code == "Forbidden.NoPermission"
    assert result.provider_request_id == "req_aliyun"


def test_aliyun_sms_provider_returns_structured_check_error() -> None:
    provider = AliyunSmsProvider(
        Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            aliyun_access_key_id="ak",
            aliyun_access_key_secret="secret",
            aliyun_sms_sign_name="sign",
            aliyun_sms_template_code="template",
        )
    )
    provider._client = FakeAliyunClient()

    result = provider.check_code("13800138000", "86", "123456")

    assert result.success is False
    assert result.verify_result == "ERROR"
    assert result.result_code == "Forbidden.NoPermission"
