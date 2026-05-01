from app.core.config import get_settings


def test_settings_load_from_environment(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_NAME", "LetMeFit Test Backend")
    monkeypatch.setenv("API_PREFIX", "/api-test")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-enough-length")

    try:
        settings = get_settings()

        assert settings.app_name == "LetMeFit Test Backend"
        assert settings.api_prefix == "/api-test"
        assert settings.jwt_secret_key == "test-secret-key-with-enough-length"
    finally:
        get_settings.cache_clear()
