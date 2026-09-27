"""Transport adapters for structured domain errors."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import DomainError


def domain_error_content(error: DomainError) -> dict[str, Any]:
    """Preserve the existing FastAPI ``detail`` response contract."""
    return {"detail": error.payload.get("detail", error.message)}


async def domain_error_handler(_request: Request, error: DomainError) -> JSONResponse:
    """Translate a domain rejection without exposing internal implementation data."""
    return JSONResponse(
        status_code=error.status_code,
        content=domain_error_content(error),
    )


__all__ = ["domain_error_content", "domain_error_handler"]
