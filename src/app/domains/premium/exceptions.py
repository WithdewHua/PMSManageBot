"""Typed Premium business rejections."""

from __future__ import annotations

from app.core.errors import DomainError


class PremiumAccountNotBound(DomainError, ValueError, NameError):
    """The requested Premium operation has no bound media account."""

    def __init__(self, service: str) -> None:
        normalized = service.capitalize()
        super().__init__(
            "premium.account_not_bound",
            f"请先绑定 {normalized} 账户",
            status_code=400,
            payload={"detail": f"请先绑定 {normalized} 账户"},
        )


__all__ = ["PremiumAccountNotBound"]
