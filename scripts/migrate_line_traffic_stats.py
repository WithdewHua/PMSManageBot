from datetime import datetime, timedelta

from app.config import settings
from app.databases import db
from app.databases.session import get_session
from app.log import logger
from app.models.models import LineTrafficStats
from sqlalchemy import select


def migrate_historical_traffic_data(
    start_month: str = None,
    end_month: str = None,
    batch_process: bool = True,
    confirm_cleanup: bool = False,
):
    """
    批量处理历史流量数据迁移

    Args:
        start_month: 开始月份，格式为 'YYYY-MM'，如果为 None 则自动检测最早月份
        end_month: 结束月份，格式为 'YYYY-MM'，如果为 None 则处理到上个月
        batch_process: 是否批量处理，如果为 False 则逐月确认
        confirm_cleanup: 是否自动确认清理原始数据，如果为 False 则需要手动确认每月的清理

    Returns:
        dict: 包含处理结果的详细信息
    """
    try:
        results = {
            "total_months": 0,
            "success_months": [],
            "failed_months": [],
            "skipped_months": [],
            "cleanup_months": [],
            "cleanup_failed_months": [],
            "summary": {},
        }

        # 确定处理的月份范围
        now = datetime.now(settings.TZ)
        current_month = now.strftime("%Y-%m")

        # 如果没有指定结束月份，默认处理到上个月
        if end_month is None:
            last_month = now.replace(day=1) - timedelta(days=1)
            end_month = last_month.strftime("%Y-%m")

        # 如果没有指定开始月份，自动检测数据库中最早的月份
        if start_month is None:
            with get_session() as session:
                from sqlalchemy import func

                stmt = select(func.min(LineTrafficStats.timestamp))
                earliest_record = session.execute(stmt).scalar()

            if not earliest_record:
                logger.warning("未找到任何流量数据")
                return results

            earliest_date = datetime.fromisoformat(earliest_record)
            start_month = earliest_date.strftime("%Y-%m")

        # 验证月份格式
        try:
            start_date = datetime.strptime(start_month, "%Y-%m")
            end_date = datetime.strptime(end_month, "%Y-%m")
        except ValueError as e:
            logger.error(f"月份格式错误: {e}")
            return results

        if start_date > end_date:
            logger.error("开始月份不能大于结束月份")
            return results

        if end_month >= current_month:
            logger.warning(f"结束月份 {end_month} 不能是当月或未来月份，调整为上个月")
            last_month = now.replace(day=1) - timedelta(days=1)
            end_month = last_month.strftime("%Y-%m")
            end_date = datetime.strptime(end_month, "%Y-%m")

        logger.info("开始批量处理历史流量数据迁移")
        logger.info(f"处理月份范围: {start_month} 至 {end_month}")
        logger.info(f"批量处理模式: {'是' if batch_process else '否'}")
        logger.info(f"自动清理原始数据: {'是' if confirm_cleanup else '否'}")

        # 生成月份列表
        months_to_process = []
        current_date = start_date
        while current_date <= end_date:
            month_str = current_date.strftime("%Y-%m")
            months_to_process.append(month_str)
            # 移动到下个月
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        results["total_months"] = len(months_to_process)

        print(
            f"\n即将处理 {len(months_to_process)} 个月份的数据: {', '.join(months_to_process)}"
        )

        if not batch_process:
            confirm = (
                input("是否继续处理？输入 'yes' 确认，其他任何输入取消: ")
                .strip()
                .lower()
            )
            if confirm != "yes":
                logger.info("用户取消历史数据迁移操作")
                return results

        # 逐月处理
        for month in months_to_process:
            print(f"\n{'='*50}")
            print(f"处理月份: {month}")
            print(f"{'='*50}")

            try:
                # 检查原始数据是否存在
                month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d").replace(
                    tzinfo=settings.TZ
                )
                if month_start.month == 12:
                    next_month_start = month_start.replace(
                        year=month_start.year + 1, month=1
                    )
                else:
                    next_month_start = month_start.replace(month=month_start.month + 1)

                month_start_str = month_start.isoformat()
                next_month_start_str = next_month_start.isoformat()

                with get_session() as session:
                    from sqlalchemy import func

                    stmt = (
                        select(func.count())
                        .select_from(LineTrafficStats)
                        .where(
                            LineTrafficStats.timestamp >= month_start_str,
                            LineTrafficStats.timestamp < next_month_start_str,
                        )
                    )
                    original_count = session.execute(stmt).scalar()

                if original_count == 0:
                    logger.info(f"月份 {month} 没有原始数据，跳过处理")
                    results["skipped_months"].append(month)
                    continue

                logger.info(f"月份 {month} 包含 {original_count:,} 条原始记录")

                # 第一步：数据聚合
                success, message = db.aggregate_monthly_traffic_data(month)

                if success:
                    logger.info(f"✅ 月份 {month} 聚合成功: {message}")
                    results["success_months"].append(month)

                    # 第二步：数据清理
                    should_cleanup = confirm_cleanup
                    if not batch_process and not confirm_cleanup:
                        print(
                            f"\n月份 {month} 聚合成功，原始数据有 {original_count:,} 条记录"
                        )
                        cleanup_confirm = (
                            input("是否清理此月份的原始数据？输入 'yes' 确认清理: ")
                            .strip()
                            .lower()
                        )
                        should_cleanup = cleanup_confirm == "yes"

                    if should_cleanup:
                        cleanup_success, cleanup_message = (
                            db.cleanup_monthly_traffic_data(month)
                        )
                        if cleanup_success:
                            logger.info(f"🗑️ 月份 {month} 清理成功: {cleanup_message}")
                            results["cleanup_months"].append(month)
                        else:
                            logger.error(f"❌ 月份 {month} 清理失败: {cleanup_message}")
                            results["cleanup_failed_months"].append(month)
                    else:
                        logger.info(f"⏭️ 月份 {month} 跳过清理，仅完成数据聚合")
                else:
                    logger.error(f"❌ 月份 {month} 聚合失败: {message}")
                    results["failed_months"].append(month)

                # 如果不是批量处理，每月处理后暂停
                if not batch_process and month != months_to_process[-1]:
                    input("\n按回车键继续处理下一个月份...")

            except Exception as e:
                error_msg = f"处理月份 {month} 时发生异常: {e}"
                logger.error(error_msg)
                results["failed_months"].append(month)

        # 生成处理摘要
        results["summary"] = {
            "total_processed": len(results["success_months"])
            + len(results["failed_months"]),
            "success_rate": len(results["success_months"])
            / max(results["total_months"], 1)
            * 100,
            "cleanup_rate": len(results["cleanup_months"])
            / max(len(results["success_months"]), 1)
            * 100
            if results["success_months"]
            else 0,
        }

        print(f"\n{'='*60}")
        print("历史数据迁移处理完成")
        print(f"{'='*60}")
        print(f"总处理月份: {results['total_months']}")
        print(f"聚合成功: {len(results['success_months'])} 个月")
        print(f"聚合失败: {len(results['failed_months'])} 个月")
        print(f"跳过处理: {len(results['skipped_months'])} 个月")
        print(f"清理成功: {len(results['cleanup_months'])} 个月")
        print(f"清理失败: {len(results['cleanup_failed_months'])} 个月")
        print(f"成功率: {results['summary']['success_rate']:.1f}%")

        if results["success_months"]:
            print(f"\n✅ 聚合成功的月份: {', '.join(results['success_months'])}")
        if results["failed_months"]:
            print(f"\n❌ 聚合失败的月份: {', '.join(results['failed_months'])}")
        if results["cleanup_months"]:
            print(f"\n🗑️ 清理成功的月份: {', '.join(results['cleanup_months'])}")
        if results["cleanup_failed_months"]:
            print(f"\n⚠️ 清理失败的月份: {', '.join(results['cleanup_failed_months'])}")

        return results

    except Exception as e:
        error_msg = f"批量处理历史流量数据迁移失败: {e}"
        logger.error(error_msg)
        results["error"] = error_msg
        return results


if __name__ == "__main__":
    logger.info("启动历史流量数据迁移脚本...")

    # 批量迁移所有历史数据，自动进行清理
    migrate_historical_traffic_data(confirm_cleanup=True)

    # 交互式迁移特定月份
    # migrate_historical_traffic_data('2025-06', '2025-08', batch_process=False)
