"""数据迁移脚本：将 Redis 中的配置数据迁移到数据库
包括：免费高级线路、线路标签、幸运大转盘配置
"""

from __future__ import annotations

import json

from app.core.log import logger
from app.core.redis import Redis
from app.domains.lines import catalog as line_catalog
from app.domains.luckywheel import service as luckywheel_service
from app.domains.luckywheel.schemas import LuckyWheelConfig


def migrate_free_premium_lines() -> None:
    """迁移免费高级线路数据"""
    logger.info("开始迁移免费高级线路数据...")
    try:
        redis_client = Redis(db=2).get_connection()
        cache_key = "emby_free_premium_lines:free_lines"

        free_lines_str = redis_client.get(cache_key)
        if free_lines_str:
            if isinstance(free_lines_str, bytes):
                free_lines_str = free_lines_str.decode("utf-8")
            free_lines = [
                line.strip() for line in free_lines_str.split(",") if line.strip()
            ]

            if free_lines:
                success = line_catalog.set_free_premium_lines(free_lines)
                if success:
                    logger.info(
                        f"成功迁移 {len(free_lines)} 条免费高级线路: {free_lines}"
                    )
                else:
                    logger.error("迁移免费高级线路失败")
            else:
                logger.info("没有找到免费高级线路数据")
        else:
            logger.info("Redis 中没有免费高级线路数据")
    except Exception as e:
        logger.error(f"迁移免费高级线路时出错: {e!s}")


def migrate_line_tags() -> None:
    """迁移线路标签数据"""
    logger.info("开始迁移线路标签数据...")
    try:
        redis_client = Redis(db=2).get_connection()
        cache_prefix = "emby_line_tags:"

        # 扫描所有线路标签键
        count = 0
        for key in redis_client.scan_iter(match=f"{cache_prefix}*"):
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            line_name = key.removeprefix(cache_prefix)
            tags_str = redis_client.get(key)
            if isinstance(tags_str, bytes):
                tags_str = tags_str.decode("utf-8")

            if tags_str:
                tags = [tag.strip() for tag in tags_str.split(",") if tag.strip()]

                if tags:
                    success = line_catalog.set_line_tags(line_name, tags)
                    if success:
                        count += 1
                        logger.info(f"成功迁移线路 {line_name} 的标签: {tags}")
                    else:
                        logger.error(f"迁移线路 {line_name} 的标签失败")

        logger.info(f"共迁移 {count} 条线路标签数据")
    except Exception as e:
        logger.error(f"迁移线路标签时出错: {e!s}")


def migrate_lucky_wheel_config() -> None:
    """迁移幸运大转盘配置数据"""
    logger.info("开始迁移幸运大转盘配置数据...")
    try:
        redis_client = Redis(db=0).get_connection()

        # 迁移主配置
        config_key = "luckywheel:config"
        config_data = redis_client.get(config_key)
        if config_data:
            if isinstance(config_data, bytes):
                config_data = config_data.decode("utf-8")
            raw_config = (
                json.loads(config_data) if isinstance(config_data, str) else config_data
            )
            config = (
                LuckyWheelConfig.model_validate(raw_config)
                if isinstance(raw_config, dict)
                else LuckyWheelConfig.model_validate_json(config_data)
            )
            success = luckywheel_service.save_wheel_config(config)
            if success:
                logger.info("成功迁移幸运大转盘主配置")
            else:
                logger.error("迁移幸运大转盘主配置失败")
        else:
            logger.info("Redis 中没有幸运大转盘主配置数据")

        # 迁移随机性配置
        randomness_key = "luckywheel:randomness_config"
        randomness_data = redis_client.get(randomness_key)
        if randomness_data:
            if isinstance(randomness_data, bytes):
                randomness_data = randomness_data.decode("utf-8")
            randomness_dict = (
                json.loads(randomness_data)
                if isinstance(randomness_data, str)
                else randomness_data
            )
            luckywheel_service.save_randomness_config(randomness_dict)
            logger.info("成功迁移幸运大转盘随机性配置")
        else:
            logger.info("Redis 中没有幸运大转盘随机性配置数据")
    except Exception as e:
        logger.error(f"迁移幸运大转盘配置时出错: {e!s}")


def main() -> None:
    """主迁移函数"""
    logger.info("=" * 60)
    logger.info("开始数据迁移：Redis -> Database")
    logger.info("=" * 60)

    # 执行迁移
    migrate_free_premium_lines()
    logger.info("-" * 60)

    migrate_line_tags()
    logger.info("-" * 60)

    migrate_lucky_wheel_config()
    logger.info("-" * 60)

    logger.info("=" * 60)
    logger.info("数据迁移完成！")
    logger.info("=" * 60)
    logger.info("")
    logger.info("注意：")
    logger.info("1. 请检查上述日志，确认所有数据都已成功迁移")
    logger.info("2. 迁移完成后，Redis 中的旧数据仍然保留，不会自动删除")
    logger.info("3. 确认系统运行正常后，可以手动清理 Redis 中的旧数据")
    logger.info("4. 建议先在测试环境中验证迁移结果")


if __name__ == "__main__":
    main()
