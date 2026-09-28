"""Dependency-free value types for luckywheel integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FreeSpinProgress:
    """Progress supplied by an activity that grants free spins."""

    enabled: bool
    hands_since_freespin: int
    hand_threshold: int


class FreeSpinProgressProvider(Protocol):
    """Callable interface for source-owned free-spin progress."""

    def __call__(self, tg_id: int) -> FreeSpinProgress: ...


__all__ = ["FreeSpinProgress", "FreeSpinProgressProvider"]
