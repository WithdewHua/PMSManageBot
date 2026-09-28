import json
import time

from sqlalchemy import BIGINT, Index, String, Text, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, get_session
from app.core.log import logger


class SystemConfig(Base):
    """System configuration model - unified config storage

    Supports different config types:
    - free_premium_line: Free premium lines (key=line_name, value=enabled)
    - line_tag: Line tags (key=line_name, value=comma-separated tags)
    - lucky_wheel: Lucky wheel config (key=config/randomness_config, value=json)
    - blackjack: 21 点配置 (key=config, value=json；key=jackpot_fund, value=幸运奖池余额)
    - prediction_market: 大预言家配置 (key=config/glory_fund, value=json)

    注意：`prediction_market.glory_fund`（荣耀奖池余额）**仅由大预言家注入**。
    21 点的抽水注入的是自有的 `blackjack.jackpot_fund`（幸运奖池，余额对玩家
    可见），两者互不相干。两个余额都以**小数字符串**存储——21 点的单手注入天然
    是小数，而荣耀奖池的读取端曾用 `int()` 解析、读到小数即抛错并把余额静默清零，
    该隐患已一并修掉。

    锦标赛只在 `blackjack.config` 里放全局旋钮（通知开关、提醒提前量、勋章加成
    上限、创建赛事的表单默认值）。**每场赛事的实际参数落在 `blackjack_tournament`
    表自己的列上**，不进本表——赛事参数须逐场快照且赛中不可改，而本表是全局
    可变配置，把两者混在一起就失去了「改配置不影响已创建赛事」这个保证。
    """

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    config_type: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # 配置类型: free_premium_line, line_tag, lucky_wheel
    config_key: Mapped[str] = mapped_column(String, nullable=False)  # 配置键
    config_value: Mapped[str] = mapped_column(Text, nullable=False)  # 配置值
    created_at: Mapped[int] = mapped_column(BIGINT, nullable=False)
    updated_at: Mapped[int] = mapped_column(BIGINT, nullable=False)

    __table_args__ = (
        UniqueConstraint("config_type", "config_key", name="uq_config_type_key"),
        Index("idx_config_type_key", "config_type", "config_key"),
    )


class SystemConfigRepository:
    def get_system_config(self, config_type: str, config_key: str) -> str | None:
        """
        获取系统配置

        Args:
            config_type: 配置类型 (free_premium_line, line_tag, lucky_wheel)
            config_key: 配置键

        Returns:
            配置值，如果不存在返回 None
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig.config_value).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                result = session.execute(stmt).scalar_one_or_none()
                return result
        except Exception as e:
            logger.error(
                f"获取系统配置失败 (type={config_type}, key={config_key}): {e!s}"
            )
            return None

    def set_system_config(
        self, config_type: str, config_key: str, config_value: str
    ) -> bool:
        """
        设置系统配置（更新或插入）

        Args:
            config_type: 配置类型
            config_key: 配置键
            config_value: 配置值

        Returns:
            是否成功
        """
        try:
            current_time = int(time.time())
            with get_session() as session:
                # 尝试查找现有配置
                stmt = select(SystemConfig).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                existing_config = session.execute(stmt).scalar_one_or_none()

                if existing_config:
                    # 更新现有配置
                    existing_config.config_value = config_value
                    existing_config.updated_at = current_time
                else:
                    # 插入新配置
                    new_config = SystemConfig(
                        config_type=config_type,
                        config_key=config_key,
                        config_value=config_value,
                        created_at=current_time,
                        updated_at=current_time,
                    )
                    session.add(new_config)

                logger.info(f"设置系统配置成功 (type={config_type}, key={config_key})")
                return True
        except Exception as e:
            logger.error(
                f"设置系统配置失败 (type={config_type}, key={config_key}): {e!s}"
            )
            return False

    def delete_system_config(self, config_type: str, config_key: str) -> bool:
        """
        删除系统配置

        Args:
            config_type: 配置类型
            config_key: 配置键

        Returns:
            是否成功
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig).where(
                    SystemConfig.config_type == config_type,
                    SystemConfig.config_key == config_key,
                )
                config = session.execute(stmt).scalar_one_or_none()

                if config:
                    session.delete(config)
                    logger.info(
                        f"删除系统配置成功 (type={config_type}, key={config_key})"
                    )
                    return True
                else:
                    logger.info(
                        f"系统配置不存在 (type={config_type}, key={config_key})"
                    )
                    return True
        except Exception as e:
            logger.error(
                f"删除系统配置失败 (type={config_type}, key={config_key}): {e!s}"
            )
            return False

    def get_all_configs_by_type(self, config_type: str) -> dict:
        """
        获取指定类型的所有配置

        Args:
            config_type: 配置类型

        Returns:
            配置字典 {config_key: config_value}
        """
        try:
            with get_session() as session:
                stmt = select(SystemConfig.config_key, SystemConfig.config_value).where(
                    SystemConfig.config_type == config_type
                )
                results = session.execute(stmt).all()
                return {row[0]: row[1] for row in results}
        except Exception as e:
            logger.error(f"获取所有配置失败 (type={config_type}): {e!s}")
            return {}


# --------------------------------------------------------------------------- #
# 事务内配置读写（调用方持有 session 与事务边界）
#
# 这些模块级函数不吞异常：读取失败不能被当成“没有配置”。旧的
# `SystemConfigRepository` 保留原签名，供尚未迁移的调用方使用。
# --------------------------------------------------------------------------- #


def get_tx(
    session,
    config_type: str,
    config_key: str,
    *,
    for_update: bool = False,
) -> str | None:
    """在调用方事务里读取配置值；`for_update=True` 时对配置行加锁。

    PostgreSQL 上行锁让“读出—判断—写回”串行化；SQLite 会忽略 `FOR UPDATE`，
    但其写锁本身已串行化。列查询不经过 ORM 标识映射，锁住后读到的一定是最新值。
    """
    stmt = select(SystemConfig.config_value).where(
        SystemConfig.config_type == config_type,
        SystemConfig.config_key == config_key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return session.execute(stmt).scalar_one_or_none()


def upsert_tx(session, config_type: str, config_key: str, value: str) -> None:
    """在调用方事务里写入配置值（存在则更新，不存在则插入）。"""
    now = int(time.time())
    updated = session.execute(
        update(SystemConfig)
        .where(
            SystemConfig.config_type == config_type,
            SystemConfig.config_key == config_key,
        )
        .values(config_value=value, updated_at=now)
    )
    if updated.rowcount == 0:
        session.add(
            SystemConfig(
                config_type=config_type,
                config_key=config_key,
                config_value=value,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()


def compare_and_update_tx(
    session,
    config_type: str,
    config_key: str,
    predicate,
    **changes,
) -> bool:
    """在配置行锁内对 JSON 文档做条件更新，返回是否真的改动了。

    读出文档 → `predicate(document)` 为真才合并 `changes` 并写回。配置行不存在
    或文档无法解析时返回 `False`，不产生副作用；这样“一次性开关”在并发下只会
    被消费一次，其余调用读到已翻转的值而放弃。

    这是 design 「领域配置的 JSON 文档存储」的 `compare_and_update(predicate,
    **changes)`，按项目约定带上 `_tx` 后缀并由调用方提供 session。
    """
    raw = get_tx(session, config_type, config_key, for_update=True)
    if raw is None:
        return False
    try:
        document = json.loads(raw)
    except (TypeError, ValueError) as error:
        logger.error(
            f"配置文档无法解析 (type={config_type}, key={config_key}): {error!s}"
        )
        return False
    if not isinstance(document, dict) or not predicate(document):
        return False
    document.update(changes)
    upsert_tx(
        session,
        config_type,
        config_key,
        json.dumps(document, ensure_ascii=False),
    )
    return True


__all__ = [
    "SystemConfig",
    "SystemConfigRepository",
    "compare_and_update_tx",
    "get_tx",
    "upsert_tx",
]
