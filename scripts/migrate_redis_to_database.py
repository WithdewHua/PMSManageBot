#!/usr/bin/env python3
"""
数据迁移脚本：将 Redis 中的配置数据迁移到数据库
包括：免费高级线路、线路标签、幸运大转盘配置
"""

from app.databases.db import db
from app.databases.redis import Redis
from app.log import logger


def migrate_free_premium_lines():
    """迁移免费高级线路数据"""
    logger.info("开始迁移免费高级线路数据...")
    try:
        redis_client = Redis(db=2).get_connection()
        cache_key = "emby_free_premium_lines:free_lines"

        free_lines_str = redis_client.get(cache_key)
        if free_lines_str:
            free_lines = free_lines_str.decode("utf-8").split(",")
            free_lines = [line.strip() for line in free_lines if line.strip()]

            if free_lines:
                success = db.set_free_premium_lines(free_lines)
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
        logger.error(f"迁移免费高级线路时出错: {str(e)}")


def migrate_line_tags():
    """迁移线路标签数据"""
    logger.info("开始迁移线路标签数据...")
    try:
        redis_client = Redis(db=2).get_connection()
        cache_prefix = "emby_line_tags:"

        # 扫描所有线路标签键
        count = 0
        for key in redis_client.scan_iter(match=f"{cache_prefix}*"):
            line_name = key.decode("utf-8").removeprefix(cache_prefix)
            tags_str = redis_client.get(key)

            if tags_str:
                tags = tags_str.decode("utf-8").split(",")
                tags = [tag.strip() for tag in tags if tag.strip()]

                if tags:
                    success = db.set_line_tags(line_name, tags)
                    if success:
                        count += 1
                        logger.info(f"成功迁移线路 {line_name} 的标签: {tags}")
                    else:
                        logger.error(f"迁移线路 {line_name} 的标签失败")

        logger.info(f"共迁移 {count} 条线路标签数据")
    except Exception as e:
        logger.error(f"迁移线路标签时出错: {str(e)}")


def migrate_lucky_wheel_config():
    """迁移幸运大转盘配置数据"""
    logger.info("开始迁移幸运大转盘配置数据...")
    try:
        redis_client = Redis(db=0).get_connection()

        # 迁移主配置
        config_key = "luckywheel:config"
        config_data = redis_client.get(config_key)
        if config_data:
            config_str = config_data.decode("utf-8")
            success = db.set_lucky_wheel_config("config", config_str)
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
            randomness_str = randomness_data.decode("utf-8")
            success = db.set_lucky_wheel_config("randomness_config", randomness_str)
            if success:
                logger.info("成功迁移幸运大转盘随机性配置")
            else:
                logger.error("迁移幸运大转盘随机性配置失败")
        else:
            logger.info("Redis 中没有幸运大转盘随机性配置数据")
    except Exception as e:
        logger.error(f"迁移幸运大转盘配置时出错: {str(e)}")


def main():
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
