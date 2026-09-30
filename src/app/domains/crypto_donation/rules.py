"""Pure validation of signed callback amounts against stored orders."""

from decimal import Decimal, InvalidOperation


def amounts_match(order_amount: object, callback_amount: object) -> bool:
    """Preserve the existing two-decimal comparison without trusting input totals."""
    try:
        quantizer = Decimal("0.01")
        return Decimal(str(order_amount)).quantize(quantizer) == Decimal(
            str(callback_amount)
        ).quantize(quantizer)
    except (InvalidOperation, TypeError, ValueError):
        return False
