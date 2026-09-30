"""Donation domain exceptions."""

from __future__ import annotations

from app.core import errors


class DonationError(errors.DomainError):
    """Base exception for donation domain rejections."""


class DonationRegistrationNotFound(DonationError):
    def __init__(self, message: str = "捐赠登记记录不存在") -> None:
        super().__init__(
            "donation_registration_not_found",
            message,
            status_code=404,
        )


class DonationRegistrationNotPending(DonationError):
    def __init__(self, status: str) -> None:
        super().__init__(
            "donation_registration_not_pending",
            f"此登记记录状态为 {status}，无法处理",
            status_code=400,
            payload={"current_status": status},
        )


class DonationUserNotFound(DonationError):
    def __init__(self, message: str = "用户不存在") -> None:
        super().__init__(
            "donation_user_not_found",
            message,
            status_code=400,
        )


class DonationInvalidAmount(DonationError):
    def __init__(self, message: str = "参数错误") -> None:
        super().__init__(
            "donation_invalid_amount",
            message,
            status_code=400,
        )


class DonationCreateFailed(DonationError):
    def __init__(self, message: str = "创建捐赠登记失败") -> None:
        super().__init__(
            "donation_create_failed",
            message,
            status_code=500,
        )


__all__ = [
    "DonationCreateFailed",
    "DonationError",
    "DonationInvalidAmount",
    "DonationRegistrationNotFound",
    "DonationRegistrationNotPending",
    "DonationUserNotFound",
]
