"""Typed references and results for credit-ledger mutations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Literal

CreditAccountKind = Literal["tg", "plex", "emby"]


@dataclass(frozen=True)
class CreditAccount:
    """Identify exactly one row in one of the three credit-bearing tables."""

    kind: CreditAccountKind
    identifier: int | str

    def __post_init__(self) -> None:
        if self.kind not in {"tg", "plex", "emby"}:
            raise ValueError(f"unsupported credit account kind: {self.kind}")
        if isinstance(self.identifier, bool) or not self.identifier:
            raise ValueError("credit account identifier must be non-empty")
        if self.kind in {"tg", "plex"}:
            if isinstance(self.identifier, float) or not str(self.identifier).isdigit():
                raise ValueError(
                    f"{self.kind} credit account identifier must be an integer"
                )
            normalized = int(self.identifier)
            if normalized <= 0:
                raise ValueError("credit account identifier must be positive")
            object.__setattr__(self, "identifier", normalized)
        elif not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("emby credit account identifier must be non-empty")

    @classmethod
    def tg(cls, tg_id: int) -> CreditAccount:
        return cls("tg", tg_id)

    @classmethod
    def plex(cls, plex_id: int) -> CreditAccount:
        return cls("plex", plex_id)

    @classmethod
    def emby(cls, emby_id: str) -> CreditAccount:
        return cls("emby", emby_id)

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.identifier}"


@dataclass(frozen=True)
class CreditMutation:
    """Result of a locked delta mutation, including post-commit cache keys."""

    account: CreditAccount
    before: float
    after: float
    delta: float
    cache_keys: tuple[str, ...]


@dataclass(frozen=True)
class CreditTransfer:
    """Committed transfer result returned to the interface layer."""

    sender: CreditAccount
    recipient: CreditAccount
    amount: float
    fee: float
    current_sender_balance: float
    cache_keys: tuple[str, ...]


def validate_amount(amount: float | Decimal) -> float:
    """Accept only finite positive credit deltas without silently rounding them."""
    if isinstance(amount, bool):
        raise TypeError("credit amount must be finite and positive")
    try:
        normalized = float(Decimal(str(amount)))
    except (InvalidOperation, ValueError, OverflowError) as error:
        raise ValueError("credit amount must be finite and positive") from error
    if not isfinite(normalized) or normalized <= 0:
        raise ValueError("credit amount must be finite and positive")
    return normalized
