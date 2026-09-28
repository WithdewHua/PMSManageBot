"""Luckywheel workflows with caller-owned atomic spin transactions."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.log import logger
from app.domains.credits import service as credits_service
from app.domains.credits.types import CreditAccount
from app.domains.luckywheel import config as wheel_config
from app.domains.luckywheel import exceptions as luckywheel_exceptions
from app.domains.luckywheel import notifications as luckywheel_notifications
from app.domains.luckywheel import repository
from app.domains.luckywheel import rules as luckywheel_rules
from app.domains.luckywheel.schemas import (
    LuckyWheelConfig,
    LuckyWheelConfigUpdateRequest,
    LuckyWheelItem,
    LuckyWheelSpinResult,
    LuckyWheelTenSpinResult,
)
from app.domains.luckywheel.types import FreeSpinProgressProvider
from app.domains.premium import service as premium_service

DEFAULT_WHEEL_CONFIG = wheel_config.DEFAULT_WHEEL_CONFIG
RandomnessConfig = luckywheel_rules.RandomnessConfig


@dataclass(frozen=True)
class _CommittedSpin:
    result: LuckyWheelSpinResult
    invite_awarded: bool
    privileged: bool
    premium_services: tuple[str, ...]


def get_wheel_config() -> LuckyWheelConfig:
    try:
        return wheel_config.get_wheel_config()
    except luckywheel_exceptions.LuckywheelError:
        raise
    except Exception as error:
        raise luckywheel_exceptions.config_load_failed() from error


def save_wheel_config(config: LuckyWheelConfig) -> bool:
    return wheel_config.save_wheel_config(config)


def update_wheel_config(
    config_update_request: LuckyWheelConfigUpdateRequest,
) -> None:
    total_probability = sum(item.probability for item in config_update_request.items)
    if abs(total_probability - 100.0) > 0.01:
        raise luckywheel_exceptions.invalid_probability_total(total_probability)

    current_config = get_wheel_config()
    new_config = LuckyWheelConfig(
        items=config_update_request.items,
        cost_credits=(
            config_update_request.cost_credits or current_config.cost_credits
        ),
        min_credits_required=(
            config_update_request.min_credits_required
            or current_config.min_credits_required
        ),
        gen_privileged_code=config_update_request.gen_privileged_code,
    )
    try:
        saved = save_wheel_config(new_config)
    except Exception as error:
        raise luckywheel_exceptions.update_failed() from error
    if saved is False:
        raise luckywheel_exceptions.config_save_failed()


def get_user_status(tg_id: int) -> dict:
    config = get_wheel_config()
    current_credits = credits_service.read_optional(CreditAccount.tg(int(tg_id)))
    if current_credits is None:
        raise luckywheel_exceptions.user_status_failed()
    return {
        "can_participate": current_credits >= config.min_credits_required,
        "current_credits": current_credits,
        "min_credits_required": config.min_credits_required,
        "cost_credits": config.cost_credits,
    }


def get_randomness_config() -> dict:
    try:
        return wheel_config.get_randomness_config()
    except luckywheel_exceptions.LuckywheelError:
        raise
    except Exception as error:
        raise luckywheel_exceptions.randomness_read_failed() from error


def save_randomness_config(config: dict) -> None:
    try:
        if "protection_threshold" in config:
            threshold = float(config["protection_threshold"])
            if not (0 < threshold <= 50):
                raise luckywheel_exceptions.randomness_write_failed()
        if "protection_factor" in config:
            factor = float(config["protection_factor"])
            if not (1.0 <= factor <= 3.0):
                raise luckywheel_exceptions.randomness_write_failed()
    except luckywheel_exceptions.LuckywheelError:
        raise
    except (TypeError, ValueError, OverflowError) as error:
        raise luckywheel_exceptions.randomness_write_failed() from error
    try:
        if not wheel_config.save_randomness_config(config):
            raise luckywheel_exceptions.randomness_write_failed()
    except luckywheel_exceptions.LuckywheelError:
        raise
    except Exception as error:
        raise luckywheel_exceptions.randomness_write_failed() from error


def update_randomness_config(config_data: dict) -> None:
    try:
        current_config = get_randomness_config()
        updated_config = current_config.copy()
        updated_config.update(config_data)
        save_randomness_config(updated_config)
    except luckywheel_exceptions.LuckywheelError:
        raise
    except Exception as error:
        raise luckywheel_exceptions.update_failed() from error


def random_select_winner(
    items: list[LuckyWheelItem], user_id: int | None = None
) -> LuckyWheelItem:
    return luckywheel_rules.pick_prize(
        items,
        user_id=user_id,
        randomness=get_randomness_config(),
    )


def get_randomness_stats(
    items: list[LuckyWheelItem],
    iterations: int = 10000,
    randomness: dict | None = None,
) -> dict:
    if not items or iterations <= 0:
        return {}
    win_counts = {item.name: 0 for item in items}
    for _ in range(iterations):
        try:
            winner = luckywheel_rules.pick_prize(
                items,
                randomness=randomness or luckywheel_rules.RandomnessConfig.to_dict(),
            )
            win_counts[winner.name] += 1
        except Exception as error:
            logger.warning(f"转盘随机性模拟单次抽取失败: {error}")
            continue
    total_probability = sum(item.probability for item in items if item.probability > 0)
    stats = {}
    for item in items:
        if item.probability > 0:
            actual_rate = (win_counts[item.name] / iterations) * 100
            expected_rate = (item.probability / total_probability) * 100
            deviation = abs(actual_rate - expected_rate)
            stats[item.name] = {
                "expected_rate": round(expected_rate, 2),
                "actual_rate": round(actual_rate, 2),
                "deviation": round(deviation, 2),
                "win_count": win_counts[item.name],
                "is_fair": deviation < 1.0,
            }
    return stats


def get_wheel_stats() -> dict:
    return repository.get_wheel_stats()


def get_user_wheel_stats(tg_id: int) -> dict:
    return repository.get_user_wheel_stats(int(tg_id))


def _to_committed_spin(data: dict) -> _CommittedSpin:
    return _CommittedSpin(
        result=LuckyWheelSpinResult(
            item=LuckyWheelItem(
                name=str(data["item_name"]),
                probability=float(data["item_probability"]),
            ),
            credits_change=float(data["credits_change"]),
            current_credits=float(data["current_credits"]),
            used_free_spin=bool(data["used_free_spin"]),
            free_spin_source=data.get("free_spin_source"),
        ),
        invite_awarded=bool(data["invite_awarded"]),
        privileged=bool(data["privileged"]),
        premium_services=tuple(data["premium_services"]),
    )


async def _post_commit(
    spins: list[_CommittedSpin], tg_id: int, *, repeat_privileged_notice: bool = False
) -> None:
    services = tuple(
        dict.fromkeys(service for spin in spins for service in spin.premium_services)
    )
    if services:
        try:
            premium_service.sync_premium_media_access(int(tg_id), services)
        except Exception as error:
            logger.warning(f"转盘 Premium 权限同步失败 (tg_id={tg_id}): {error}")
    for spin in spins:
        if spin.invite_awarded:
            try:
                await luckywheel_notifications.notify_invite_code_awarded(
                    int(tg_id), privileged=spin.privileged
                )
            except Exception as error:
                logger.error(f"转盘邀请码通知失败 (tg_id={tg_id}): {error}")
    if repeat_privileged_notice and any(spin.privileged for spin in spins):
        try:
            await luckywheel_notifications.notify_invite_code_awarded(
                int(tg_id), privileged=True
            )
        except Exception as error:
            logger.error(f"转盘邀请码通知失败 (tg_id={tg_id}): {error}")


async def spin(
    tg_id: int,
    *,
    use_free_spin: bool = True,
    config: LuckyWheelConfig | None = None,
) -> LuckyWheelSpinResult:
    """Execute a paid-or-free single spin and notify only after commit."""
    current_config = config or get_wheel_config()
    winner = luckywheel_rules.pick_prize(
        current_config.items,
        user_id=int(tg_id),
        randomness=wheel_config.get_randomness_config(),
    )
    data = repository.spin(
        tg_id=int(tg_id),
        config=current_config,
        winner_name=winner.name,
        winner_probability=winner.probability,
        use_free_spin=use_free_spin,
    )
    committed = _to_committed_spin(data)
    await _post_commit([committed], int(tg_id))
    return committed.result


async def execute_single_spin(
    config: LuckyWheelConfig,
    user_id: int,
    current_credits: float,
    *,
    cost_credits: float | None = None,
    source: str = "paid",
) -> tuple[LuckyWheelSpinResult, float, bool]:
    """Compatibility workflow for callers that already claimed a free-spin row."""
    del current_credits
    winner = luckywheel_rules.pick_prize(
        config.items,
        user_id=int(user_id),
        randomness=wheel_config.get_randomness_config(),
    )
    data = repository.spin(
        tg_id=int(user_id),
        config=config,
        winner_name=winner.name,
        winner_probability=winner.probability,
        use_free_spin=False,
        enforce_minimum=False,
        cost_credits_override=cost_credits,
        source_override=source,
    )
    committed = _to_committed_spin(data)
    await _post_commit([committed], int(user_id))
    return committed.result, committed.result.current_credits, committed.privileged


async def spin_ten_times(
    tg_id: int,
    *,
    config: LuckyWheelConfig | None = None,
) -> LuckyWheelTenSpinResult:
    """Execute all ten paid spins in one transaction and notify after commit."""
    current_config = config or get_wheel_config()
    randomness = wheel_config.get_randomness_config()
    winners = [
        (winner.name, float(winner.probability))
        for winner in (
            luckywheel_rules.pick_prize(
                current_config.items,
                user_id=int(tg_id),
                randomness=randomness,
            )
            for _ in range(10)
        )
    ]
    data_rows = repository.spin_ten(
        tg_id=int(tg_id), config=current_config, winners=winners
    )
    committed_spins = [_to_committed_spin(data) for data in data_rows]
    if any(spin.privileged for spin in committed_spins):
        current_config.gen_privileged_code = False

    await _post_commit(committed_spins, int(tg_id), repeat_privileged_notice=True)
    return LuckyWheelTenSpinResult(
        results=[spin.result for spin in committed_spins],
        total_credits_change=round(
            sum(spin.result.credits_change for spin in committed_spins), 2
        ),
        current_credits=committed_spins[-1].result.current_credits,
    )


def register_free_spin_progress_provider(provider: FreeSpinProgressProvider) -> None:
    repository.register_free_spin_progress_provider(provider)


def clear_free_spin_progress_provider() -> None:
    repository.clear_free_spin_progress_provider()


def free_spin_summary(tg_id: int) -> dict:
    return repository.free_spin_summary(tg_id)


def claim_unnotified_blackjack_freespins() -> list[dict]:
    return repository.claim_unnotified_blackjack_freespins()


def list_expiring_blackjack_freespins(*, within_ms: int = 86400 * 1000) -> list[dict]:
    return repository.list_expiring_blackjack_freespins(within_ms=within_ms)


def consume_free_spin(tg_id: int) -> dict | None:
    return repository.consume_free_spin(tg_id)


def release_free_spin(spin_id: int, *, claimed_at_ms: int) -> bool:
    return repository.release_free_spin(spin_id, claimed_at_ms=claimed_at_ms)


__all__ = [
    "DEFAULT_WHEEL_CONFIG",
    "claim_unnotified_blackjack_freespins",
    "clear_free_spin_progress_provider",
    "consume_free_spin",
    "execute_single_spin",
    "free_spin_summary",
    "get_randomness_config",
    "get_randomness_stats",
    "get_user_status",
    "get_user_wheel_stats",
    "get_wheel_config",
    "get_wheel_stats",
    "list_expiring_blackjack_freespins",
    "random_select_winner",
    "register_free_spin_progress_provider",
    "release_free_spin",
    "save_randomness_config",
    "save_wheel_config",
    "spin",
    "spin_ten_times",
    "update_randomness_config",
    "update_wheel_config",
]
