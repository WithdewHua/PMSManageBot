"""Typed failures for payment workflows, independent of HTTP transport."""

from app.core.errors import DomainError


class CryptoDonationError(DomainError):
    """Public rejection contract for crypto donation use cases."""


class PaymentOrderNotFound(CryptoDonationError):
    def __init__(self) -> None:
        super().__init__("payment_order_not_found", "order not found", status_code=404)


class PaymentStateRejected(CryptoDonationError):
    def __init__(self) -> None:
        super().__init__(
            "payment_state_rejected", "failed to update order status", status_code=500
        )


class PaymentAmountMismatch(CryptoDonationError):
    def __init__(self) -> None:
        super().__init__("payment_amount_mismatch", "amount mismatch")
