"""Typed business rejections for Vaultwarden account redemption."""

from __future__ import annotations

from app.core.errors import DomainError


class VaultwardenError(DomainError, ValueError):
    """Base exception for Vaultwarden business rejections."""


class VaultwardenDisabled(VaultwardenError):
    def __init__(self, message: str = "Vaultwarden 兑换功能未启用") -> None:
        super().__init__("vaultwarden_disabled", message, status_code=200)


class VaultwardenAccountNotBound(VaultwardenError):
    def __init__(self, message: str = "用户未绑定 Plex/Emby 账户") -> None:
        super().__init__("vaultwarden_account_not_bound", message, status_code=404)


class VaultwardenInvalidEmail(VaultwardenError):
    def __init__(self, message: str = "请输入有效的邮箱地址") -> None:
        super().__init__("vaultwarden_invalid_email", message, status_code=200)


class VaultwardenInsufficientCredits(VaultwardenError):
    def __init__(self, current_credits: float, required_credits: int) -> None:
        super().__init__(
            "vaultwarden_insufficient_credits",
            f"积分不足，您当前积分 {current_credits}，需要 {required_credits} 积分才能兑换 Vaultwarden 账户",
            status_code=200,
            payload={
                "current_credits": current_credits,
                "required_credits": required_credits,
            },
        )


class VaultwardenInvitationFailed(VaultwardenError):
    def __init__(
        self,
        message: str = "发送邀请失败，邮箱可能已被注册或服务出现错误，请稍后再试或联系管理员",
    ) -> None:
        super().__init__("vaultwarden_invitation_failed", message, status_code=200)


class VaultwardenRefundFailed(VaultwardenError):
    def __init__(self, message: str = "开号失败且积分退还失败") -> None:
        super().__init__("vaultwarden_refund_failed", message, status_code=500)


__all__ = [
    "VaultwardenAccountNotBound",
    "VaultwardenDisabled",
    "VaultwardenError",
    "VaultwardenInsufficientCredits",
    "VaultwardenInvalidEmail",
    "VaultwardenInvitationFailed",
    "VaultwardenRefundFailed",
]
