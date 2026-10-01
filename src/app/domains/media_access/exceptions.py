"""Typed media-access business rejections."""

from __future__ import annotations

from app.core.errors import DomainError


class MediaAccountNotBound(DomainError, ValueError):
    def __init__(self, service: str):
        super().__init__(
            "media.account_not_bound",
            f"请先绑定 {service.capitalize()} 账户",
            status_code=200,
            payload={"detail": f"请先绑定 {service.capitalize()} 账户"},
        )


class DownloadAlreadyUnlocked(DomainError, ValueError):
    def __init__(self):
        super().__init__(
            "media.download_already_unlocked",
            "下载权限已解锁，无需重复解锁",
            status_code=200,
            payload={"detail": "下载权限已解锁，无需重复解锁"},
        )


class InsufficientCredits(DomainError, ValueError):
    def __init__(self, message: str = "积分不足"):
        super().__init__(
            "media.insufficient_credits",
            message,
            status_code=400,
            payload={"detail": message},
        )
