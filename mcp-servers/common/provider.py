from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Callable, Protocol


JsonDict = dict[str, Any]


class Provider(Protocol):
    def initialize(self) -> None: ...

    def health(self) -> JsonDict: ...

    def close(self) -> None: ...


class ProviderUnavailableError(RuntimeError):
    pass


def read_secret(env_name: str, file_path: str = "") -> str:
    value = os.getenv(env_name, "")
    if value:
        return value.strip()
    if not file_path:
        return ""
    return Path(file_path).read_text(encoding="utf-8").strip()


@dataclass(slots=True)
class ManagedProvider:
    factory: Callable[[], Provider]
    mode: str
    _provider: Provider | None = field(default=None, init=False, repr=False)
    _error: str = field(default="", init=False, repr=False)

    @property
    def ready(self) -> bool:
        return self._provider is not None and not self._error

    def initialize(self) -> None:
        if self.ready:
            return
        self._error = ""
        provider: Provider | None = None
        try:
            provider = self.factory()
            provider.initialize()
            self._provider = provider
        except Exception as exc:
            if provider is not None:
                try:
                    provider.close()
                except Exception:
                    pass
            self._provider = None
            self._error = str(exc)

    def get(self) -> Provider:
        if not self.ready or self._provider is None:
            raise ProviderUnavailableError(self._error or f"{self.mode} provider is unavailable")
        return self._provider

    def health(self) -> JsonDict:
        details: JsonDict = {}
        if self._provider is not None:
            try:
                details = self._provider.health()
            except Exception as exc:
                self._error = str(exc)
        return {
            "status": "healthy" if self.ready else "unhealthy",
            "ready": self.ready,
            "mode": self.mode,
            "error": self._error,
            "details": details,
        }

    def close(self) -> None:
        provider = self._provider
        self._provider = None
        if provider is not None:
            provider.close()
