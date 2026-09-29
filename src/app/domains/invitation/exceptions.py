"""Typed invitation workflow errors."""

from app.core.errors import DomainError


class InvitationError(DomainError, ValueError):
    """Base error preserving legacy ValueError catches at public boundaries."""

    def __init__(self, code: str, message: str) -> None:
        DomainError.__init__(self, code, message)


class InvitationCodeUsed(InvitationError):
    def __init__(self) -> None:
        super().__init__("invitation_code_used", "邀请码已被使用")


class InvitationCodeNotFound(InvitationError):
    def __init__(self) -> None:
        super().__init__("invitation_code_not_found", "邀请码不存在")


class InvitationAccountNotFound(InvitationError):
    def __init__(self) -> None:
        super().__init__("invitation_account_not_found", "用户未绑定 Plex/Emby 账户")


class InvitationRejected(InvitationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


__all__ = [
    "InvitationAccountNotFound",
    "InvitationCodeNotFound",
    "InvitationCodeUsed",
    "InvitationError",
    "InvitationRejected",
]
