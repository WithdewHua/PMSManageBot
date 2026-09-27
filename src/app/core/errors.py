"""Structured business errors shared by API and domain services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DomainError(Exception):
    """A business rejection that can cross a transport boundary safely."""

    code: str
    status_code: int
    payload: dict[str, Any]

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        payload: Mapping[str, Any] | None = None,
        cause: BaseException | None = None,
    ) -> None:
        if not code or not code.strip():
            raise ValueError("domain error code must not be empty")
        if status_code < 100 or status_code > 599:
            raise ValueError("domain error status code must be valid HTTP status")
        self.code = code
        self.status_code = status_code
        self.payload = dict(payload or {})
        self.payload.setdefault("code", code)
        self.payload.setdefault("message", message)
        super().__init__(message)
        if cause is not None:
            self.__cause__ = cause

    @property
    def message(self) -> str:
        """Return the stable user-facing or log-facing message."""
        return str(self)

    def as_response(self) -> dict[str, Any]:
        """Return the structured response payload used by the API handler."""
        return dict(self.payload)


__all__ = ["DomainError"]
