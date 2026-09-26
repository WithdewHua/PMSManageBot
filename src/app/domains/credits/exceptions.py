"""Domain errors for credit ledger operations."""


class CreditError(ValueError):
    """Base error for a rejected credit-ledger operation."""


class CreditAccountNotFound(CreditError):
    """The requested credit-bearing account does not exist."""

    def __init__(self, account: str) -> None:
        self.account = account
        super().__init__(f"credit account not found: {account}")


class InsufficientCredits(CreditError):
    """A deduction would make the account balance negative."""

    def __init__(self, account: str, requested: float, available: float) -> None:
        self.account = account
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient credits for {account}: requested={requested:.2f}, "
            f"available={available:.2f}"
        )
