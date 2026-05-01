import pytest

from app.auth.security import (
    access_token_expires_in_seconds,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_secret,
)
from app.auth.service import normalize_phone_number
from app.core.config import Settings
from app.core.errors import AppError


def test_normalize_mainland_phone_number() -> None:
    phone = normalize_phone_number("138-0013-8000")

    assert phone.e164 == "+8613800138000"
    assert phone.national_number == "13800138000"
    assert phone.country_code == "86"


def test_normalize_rejects_non_mainland_country_code() -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_phone_number("+11234567890")

    assert exc_info.value.code == "VALIDATION_ERROR"


def test_access_token_round_trip() -> None:
    settings = Settings(jwt_secret_key="test-secret-key-with-enough-length")

    token = create_access_token("user_test", settings)
    payload = decode_access_token(token, settings)

    assert payload["sub"] == "user_test"
    assert payload["typ"] == "access"
    assert access_token_expires_in_seconds(settings) == 1800


def test_secret_hash_uses_configured_secret() -> None:
    settings_a = Settings(jwt_secret_key="test-secret-key-with-enough-length-a")
    settings_b = Settings(jwt_secret_key="test-secret-key-with-enough-length-b")

    assert hash_secret("same-value", settings_a) != hash_secret("same-value", settings_b)


def test_refresh_token_is_opaque() -> None:
    token = create_refresh_token()

    assert token.startswith("rt_")
    assert len(token) > 30
