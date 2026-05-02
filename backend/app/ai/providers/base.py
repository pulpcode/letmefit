from abc import ABC, abstractmethod

from app.ai.types import ExtractionInput, ExtractionProviderResult
from app.core.config import Settings, get_settings
from app.core.errors import AppError


class ExtractionProvider(ABC):
    provider_name = "base"

    @abstractmethod
    def extract(self, payload: ExtractionInput) -> ExtractionProviderResult:
        raise NotImplementedError


def get_extraction_provider(settings: Settings | None = None) -> ExtractionProvider:
    from app.ai.providers.bailian import BailianExtractionProvider
    from app.ai.providers.mock import MockExtractionProvider

    settings = settings or get_settings()
    provider = settings.ai_provider.lower()
    if provider == "mock":
        return MockExtractionProvider(settings)
    if provider == "bailian":
        return BailianExtractionProvider(settings)
    raise AppError(
        "INTERNAL_ERROR",
        "AI 提取服务配置不正确",
        status_code=500,
        details={"ai_provider": settings.ai_provider},
    )
