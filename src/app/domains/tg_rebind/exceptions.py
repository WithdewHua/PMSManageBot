"""Typed failures for the manual Telegram ID reassignment workflow."""

from __future__ import annotations

from app.core.errors import DomainError
from app.domains.identity.types import TgIdReassignIssue


class TgRebindError(DomainError):
    """Base error for the explicit administrative reassignment command."""


class TgRebindRejected(TgRebindError, ValueError):
    def __init__(self, issues: list[TgIdReassignIssue]) -> None:
        self.issues = tuple(issues)
        details = "; ".join(issue.description for issue in self.issues)
        super().__init__(
            "tg_rebind_rejected", details or "Telegram ID reassignment rejected"
        )


class TgRebindAccountNotFound(TgRebindError, ValueError):
    def __init__(self, locator: str) -> None:
        self.locator = locator
        super().__init__("tg_rebind_account_not_found", f"account not found: {locator}")


class TgRebindSameId(TgRebindError, ValueError):
    def __init__(self) -> None:
        super().__init__("tg_rebind_same_id", "old and new Telegram IDs must differ")


__all__ = [
    "TgRebindAccountNotFound",
    "TgRebindError",
    "TgRebindRejected",
    "TgRebindSameId",
]
