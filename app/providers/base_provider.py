from abc import ABC, abstractmethod
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse


class BaseProvider(ABC):
    @abstractmethod  # pragma: no cover - 抽象方法, 由子类实现并测试
    async def chat_completion(self, request_data: dict[str, Any]) -> StreamingResponse:
        pass

    @abstractmethod  # pragma: no cover - 抽象方法, 由子类实现并测试
    async def get_models(self) -> JSONResponse:
        pass
