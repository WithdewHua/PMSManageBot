"""Run a disposable PostgreSQL concurrency check for privileged wheel codes."""

from __future__ import annotations

import argparse
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    return parser.parse_args()


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    args = _parse_args()
    os.environ["DATABASE_URL"] = args.url
    os.environ["DATABASE_TYPE"] = "postgresql"

    from sqlalchemy import func, select

    from app.core import db as db_module
    from app.core.config import Settings, settings
    from app.domains.credits import repository as credits_repository
    from app.domains.identity.models import Statistics
    from app.domains.invitation.models import Invitation
    from app.domains.luckywheel import config as wheel_config
    from app.domains.luckywheel import repository as wheel_repository
    from app.domains.luckywheel.models import WheelStats
    from app.model_registry import metadata

    credits_repository.invalidate_user_credits = lambda _keys: None
    original_codes = list(settings.PRIVILEGED_CODES)
    Settings.save_config_to_env_file = lambda *args, **kwargs: None

    metadata.drop_all(bind=db_module.engine)
    metadata.create_all(bind=db_module.engine)

    config = wheel_config.DEFAULT_WHEEL_CONFIG.model_copy(
        update={"gen_privileged_code": True}
    )
    with db_module.get_session() as session:
        session.add_all(
            [
                Statistics(tg_id=1, credits=100, donation=0),
                Statistics(tg_id=2, credits=100, donation=0),
            ]
        )
        wheel_config.ensure_wheel_config_tx(session, config)

    barrier = threading.Barrier(2)

    def spin(tg_id: int) -> tuple[str, object]:
        barrier.wait()
        try:
            return (
                "ok",
                wheel_repository.spin(
                    tg_id=tg_id,
                    config=config,
                    winner_name="邀请码 1 枚",
                    winner_probability=100.0,
                ),
            )
        except Exception as error:
            return "error", error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(spin, tg_id) for tg_id in (1, 2)]
        results = [future.result() for future in as_completed(futures)]

    errors = [value for kind, value in results if kind == "error"]
    _check(not errors, f"unexpected concurrent errors: {errors!r}")

    with db_module.get_session() as session:
        code_count = session.execute(select(func.count(Invitation.code))).scalar_one()
        stats_count = session.execute(select(func.count(WheelStats.id))).scalar_one()
        _check(int(code_count) == 2, f"code_count={code_count}")
        _check(int(stats_count) == 2, f"stats_count={stats_count}")
        balances = session.execute(select(Statistics.credits)).scalars().all()
        _check(all(round(float(balance), 2) == 90 for balance in balances), balances)

    privileged_delta = len(settings.PRIVILEGED_CODES) - len(original_codes)
    _check(privileged_delta == 1, f"privileged_delta={privileged_delta}")
    print(
        "luckywheel concurrency ok: "
        f"codes={code_count}, stats={stats_count}, privileged_delta={privileged_delta}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
