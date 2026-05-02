import json
from dataclasses import dataclass

from alibabacloud_dypnsapi20170525 import models as dypns_models
from alibabacloud_dypnsapi20170525.client import Client as DypnsClient
from alibabacloud_tea_openapi import models as openapi_models
from alibabacloud_tea_openapi.exceptions import AlibabaCloudException

from app.core.config import Settings, get_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class SmsSendResult:
    success: bool
    result_code: str
    provider_request_id: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class SmsCheckResult:
    success: bool
    verify_result: str
    result_code: str
    message: str | None = None


class SmsProvider:
    provider_name = "base"

    def send_code(self, phone_number: str, country_code: str) -> SmsSendResult:
        raise NotImplementedError

    def check_code(self, phone_number: str, country_code: str, code: str) -> SmsCheckResult:
        raise NotImplementedError


class MockSmsProvider(SmsProvider):
    provider_name = "mock"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def send_code(self, phone_number: str, country_code: str) -> SmsSendResult:
        return SmsSendResult(success=True, result_code="OK", provider_request_id="mock_request")

    def check_code(self, phone_number: str, country_code: str, code: str) -> SmsCheckResult:
        if code == self.settings.sms_mock_code:
            return SmsCheckResult(success=True, verify_result="PASS", result_code="OK")
        return SmsCheckResult(success=False, verify_result="FAIL", result_code="MOCK_INVALID_CODE")


class AliyunSmsProvider(SmsProvider):
    provider_name = "aliyun_dypnsapi"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: DypnsClient | None = None

    def _get_client(self) -> DypnsClient:
        if self._client is None:
            missing = [
                name
                for name, value in {
                    "ALIYUN_ACCESS_KEY_ID": self.settings.aliyun_access_key_id,
                    "ALIYUN_ACCESS_KEY_SECRET": self.settings.aliyun_access_key_secret,
                    "ALIYUN_SMS_SIGN_NAME": self.settings.aliyun_sms_sign_name,
                    "ALIYUN_SMS_TEMPLATE_CODE": self.settings.aliyun_sms_template_code,
                }.items()
                if not value
            ]
            if missing:
                raise AppError(
                    "INTERNAL_ERROR",
                    "阿里云短信配置不完整",
                    status_code=500,
                    details={"missing": missing},
                )

            config = openapi_models.Config(
                access_key_id=self.settings.aliyun_access_key_id,
                access_key_secret=self.settings.aliyun_access_key_secret,
                endpoint=self.settings.aliyun_dypns_endpoint,
            )
            self._client = DypnsClient(config)
        return self._client

    def send_code(self, phone_number: str, country_code: str) -> SmsSendResult:
        request = dypns_models.SendSmsVerifyCodeRequest(
            phone_number=phone_number,
            country_code=country_code,
            scheme_name=self.settings.aliyun_sms_scheme_name or None,
            sign_name=self.settings.aliyun_sms_sign_name,
            template_code=self.settings.aliyun_sms_template_code,
            template_param=json.dumps({"code": "##code##", "min": "5"}, separators=(",", ":")),
            code_type=1,
            code_length=6,
            valid_time=self.settings.sms_expires_in_seconds,
            interval=self.settings.sms_send_cooldown_seconds,
            duplicate_policy=1,
            return_verify_code=False,
        )
        try:
            body = self._get_client().send_sms_verify_code(request).body
        except AlibabaCloudException as exc:
            return self._provider_error_send_result(exc)
        return SmsSendResult(
            success=bool(body.success and body.code == "OK"),
            result_code=body.code or "UNKNOWN",
            provider_request_id=body.request_id,
            message=body.message,
        )

    def check_code(self, phone_number: str, country_code: str, code: str) -> SmsCheckResult:
        request = dypns_models.CheckSmsVerifyCodeRequest(
            phone_number=phone_number,
            country_code=country_code,
            scheme_name=self.settings.aliyun_sms_scheme_name or None,
            verify_code=code,
        )
        try:
            body = self._get_client().check_sms_verify_code(request).body
        except AlibabaCloudException as exc:
            return self._provider_error_check_result(exc)
        verify_result = body.model.verify_result if body.model else "UNKNOWN"
        return SmsCheckResult(
            success=bool(body.success and body.code == "OK" and verify_result == "PASS"),
            verify_result=verify_result,
            result_code=body.code or "UNKNOWN",
            message=body.message,
        )

    def _provider_error_send_result(self, exc: AlibabaCloudException) -> SmsSendResult:
        return SmsSendResult(
            success=False,
            result_code=exc.code or "ALIYUN_PROVIDER_ERROR",
            provider_request_id=exc.request_id,
            message=exc.message,
        )

    def _provider_error_check_result(self, exc: AlibabaCloudException) -> SmsCheckResult:
        return SmsCheckResult(
            success=False,
            verify_result="ERROR",
            result_code=exc.code or "ALIYUN_PROVIDER_ERROR",
            message=exc.message,
        )


def get_sms_provider() -> SmsProvider:
    settings = get_settings()
    sms_provider = settings.sms_provider.lower()
    if sms_provider == "mock":
        return MockSmsProvider(settings)
    if sms_provider == "aliyun":
        return AliyunSmsProvider(settings)
    raise AppError(
        "INTERNAL_ERROR",
        "短信服务配置不正确",
        status_code=500,
        details={"sms_provider": settings.sms_provider},
    )
