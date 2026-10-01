"""Value objects returned by the Telegram ID reassignment workflow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RebindReport:
    old_tg_id: int
    new_tg_id: int
    dry_run: bool
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    admin_configuration_warning: bool = False

    @property
    def total_rows(self) -> int:
        return sum(sum(values.values()) for values in self.counts.values())


__all__ = ["RebindReport"]
