"""Typed account-binding rejections."""

from app.core.errors import DomainError


class AccountAlreadyBound(DomainError, ValueError):
    """The media account was claimed by another Telegram account."""

    def __init__(self) -> None:
        DomainError.__init__(self, "account_already_bound", "该账户已被绑定")


__all__ = ["AccountAlreadyBound"]
