import json
import traceback
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session
from app.core.log import logger
from app.domains.identity.models import EmbyUser, PlexUser
from app.domains.traffic import rules as traffic_rules
from app.domains.traffic import service as traffic_service
from app.domains.traffic.cache import stream_traffic_cache
from app.integrations import media_tokens
from app.integrations.emby import Emby
from app.integrations.telegram.messaging import send_message_by_url


async def monthly_traffic_data_migration():
    """定时任务：月度流量数据迁移聚合"""
    try:
        # 检查今天是否是每月1号
        now = datetime.now(settings.TZ)
        if now.day != 1:
            logger.info(
                f"今天不是每月1号，跳过月度流量数据迁移任务。当前日期: {now.strftime('%Y-%m-%d')}"
            )
            return

        # 获取上个月的年月字符串
        last_month = now.replace(day=1) - timedelta(days=1)
        target_month = last_month.strftime("%Y-%m")

        logger.info(f"开始执行月度流量数据迁移任务，目标月份: {target_month}")

        # 第一步：聚合上个月的数据
        success, message = traffic_service.aggregate_monthly_traffic_data(target_month)

        if success:
            logger.info(f"数据聚合成功: {message}")

            # 第二步：清理原始数据
            cleanup_success, cleanup_message = (
                traffic_service.cleanup_monthly_traffic_data(target_month)
            )

            if cleanup_success:
                logger.info(f"数据清理成功: {cleanup_message}")

                # 通知管理员成功
                notification_message = f"""
月度流量数据迁移完成
=====================

目标月份：{target_month}
聚合结果：{message}
清理结果：{cleanup_message}

====================="""

                for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=notification_message,
                        disable_notification=True,
                    )
            else:
                # 聚合成功但清理失败
                error_message = f"月度流量数据聚合成功，但清理失败: {cleanup_message}"
                logger.error(error_message)

                for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=f"⚠️ {error_message}",
                    )
        else:
            # 聚合失败
            error_message = f"月度流量数据聚合失败: {message}"
            logger.error(error_message)

            for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                await send_message_by_url(
                    chat_id=admin_chat_id,
                    text=f"❌ {error_message}",
                )

        return success, message

    except Exception as e:
        error_msg = f"月度流量数据迁移任务执行失败: {e}"
        logger.error(error_msg)

        for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
            await send_message_by_url(
                chat_id=admin_chat_id,
                text=f"❌ {error_msg}",
            )

        return False, error_msg


async def update_line_traffic_stats(
    count: int = settings.REDIS_LINE_TRAFFIC_STATS_HANDLE_SIZE,
):
    """
    更新线路的流量数据
    """

    processing_queue = traffic_service.PROCESSING_QUEUE

    def _move_source_logs_to_processing_queue(fetch_count: int) -> list[str]:
        return traffic_service.move_source_logs_to_processing_queue(fetch_count)

    def _finalize_processing_logs(
        processed_log_count: int, failed_positions: list[int]
    ) -> None:
        traffic_service.finalize_processing_logs(processed_log_count, failed_positions)

    values = []
    transferred_count = 0
    emby = None
    try:
        remaining = max(int(count), 0)
        if remaining > 0:
            processing_values = stream_traffic_cache.redis_client.lrange(
                processing_queue, 0, remaining - 1
            )
            if processing_values:
                values.extend(processing_values)
                remaining -= len(processing_values)
                logger.info(f"从处理中队列获取 {len(processing_values)} 条日志")

        if remaining > 0:
            source_values = _move_source_logs_to_processing_queue(remaining)
            if source_values:
                logger.info(f"从源队列获取 {len(source_values)} 条日志")
                values.extend(source_values)
                transferred_count += len(source_values)
                remaining -= len(source_values)
    except Exception as e:
        logger.error(f"从 Redis 转移流量日志到处理中队列失败: {e}")
        traceback.print_exc()
        return

    if not values:
        logger.info("没有新的流量日志数据")
        return

    processed_count = 0
    acknowledged_count = 0
    duplicate_count = 0
    skipped_count = 0
    failed_positions = []

    plex_username_to_id = {}
    emby_username_to_id = {}

    try:
        with get_session() as session:
            # 加载所有 Plex 用户名到 ID 的映射
            stmt = select(PlexUser.plex_username, PlexUser.plex_id).where(
                PlexUser.plex_username.isnot(None), PlexUser.plex_id.isnot(None)
            )
            plex_users = session.execute(stmt).fetchall()
            plex_username_to_id = {
                username.lower(): plex_id
                for username, plex_id in plex_users
                if username
            }

            # 加载所有 Emby 用户名到 ID 的映射
            stmt = select(EmbyUser.emby_username, EmbyUser.emby_id).where(
                EmbyUser.emby_username.isnot(None), EmbyUser.emby_id.isnot(None)
            )
            emby_users = session.execute(stmt).fetchall()
            emby_username_to_id = {
                username.lower(): emby_id
                for username, emby_id in emby_users
                if username
            }
    except Exception as e:
        logger.error(f"加载用户ID映射失败: {e}")
        return

    try:
        # 阶段0：逐条解析（纯 CPU），收集待处理记录与各类计数
        parsed_records = []
        for index, raw_log in enumerate(values, start=1):
            try:
                # 解析 JSON 日志
                if isinstance(raw_log, bytes):
                    raw_log = raw_log.decode("utf-8")
                log_data = json.loads(raw_log)
            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析错误: {e}, 原始数据: {raw_log}")
                failed_positions.append(index)
                continue
            except Exception as e:
                logger.error(f"处理日志时发生错误: {e}, 原始数据: {raw_log}")
                failed_positions.append(index)
                continue

            # 提取时间戳
            timestamp = log_data.get("@timestamp", "")
            # 提取后端服务器信息（线路）
            backend = log_data.get("backend", "")
            # 解析 message 字段中的 nginx 访问日志
            message = log_data.get("message", "")

            parsed_log = traffic_rules.parse_access_log(message)
            if not parsed_log:
                logger.warning(f"无法解析日志格式: {message}")
                acknowledged_count += 1
                skipped_count += 1
                continue
            access_time = parsed_log["access_time"]
            url = parsed_log["url"]
            status_code = parsed_log["status_code"]
            bytes_sent = parsed_log["bytes_sent"]
            upstream = parsed_log["upstream"]
            upstream_response_time = parsed_log["upstream_response_time"]

            # 只处理成功的请求 (2xx 状态码)
            if status_code < 200 or status_code >= 300:
                acknowledged_count += 1
                skipped_count += 1
                continue

            if not traffic_rules.is_stream_request(url):
                # 只处理 /stream 路径的请求
                # 或者包含 "Original." 的请求（兼容下 emby 反代）
                logger.info(f"跳过非流媒体请求: {url}")
                acknowledged_count += 1
                skipped_count += 1
                continue

            # Parse service/token/line with the pure rules module.
            request_identity = traffic_rules.select_request_identity(url, backend)
            if request_identity is None:
                logger.warning(
                    f"缺少必要的参数 service 或 token，或缺少 backend: {url}"
                )
                acknowledged_count += 1
                skipped_count += 1
                continue
            service = request_identity["service"]
            token = request_identity["token"]
            backend = request_identity["line"]
            decoded_uri = request_identity["request_uri"]
            if not backend:
                logger.warning(f"缺少 backend 信息: {url}")
                acknowledged_count += 1
                skipped_count += 1
                continue

            formatted_timestamp = traffic_rules.format_access_timestamp(
                access_time, timestamp, timezone=settings.TZ
            )

            parsed_records.append(
                {
                    "index": index,
                    "line": backend,
                    "service": service,
                    "token": token,
                    "bytes_sent": bytes_sent,
                    "decoded_uri": decoded_uri,
                    "formatted_timestamp": formatted_timestamp,
                    "upstream": upstream,
                    "upstream_response_time": upstream_response_time,
                }
            )

        # 阶段1：解析 token -> username
        plex_tokens = {r["token"] for r in parsed_records if r["service"] == "plex"}
        emby_tokens = {r["token"] for r in parsed_records if r["service"] == "emby"}

        # 逐个查询去重后的 token：真正的优化是去重（同一 token 不再每条日志重复查），
        # 而非合并成一次 mget。逐条小请求对高延迟/抖动的远程 Redis 更稳健——
        # 单次卡顿只影响一个 token 并可重试，不会像一次大 mget 那样拖垮整批。
        plex_token_to_name = {t: media_tokens.get_plex_username(t) for t in plex_tokens}
        emby_token_to_name = {t: media_tokens.get_emby_username(t) for t in emby_tokens}

        emby_timeout_tokens = set()
        emby_miss_tokens = [t for t in emby_tokens if not emby_token_to_name.get(t)]
        if emby_miss_tokens:
            if emby is None:
                emby = Emby()
            fetched = await emby.get_emby_usernames_from_api_keys(emby_miss_tokens)
            for token, username in fetched.items():
                if username is Emby.FETCH_TIMEOUT:
                    emby_timeout_tokens.add(token)
                elif username:
                    emby_token_to_name[token] = username

        # 阶段2：组装待入库记录并分类
        to_insert = []  # (index, row, event_hash)
        for r in parsed_records:
            service = r["service"]
            token = r["token"]
            if service == "plex":
                username = plex_token_to_name.get(token)
            else:
                username = emby_token_to_name.get(token)

            # 如果无法获取到用户信息
            if not username:
                if token in emby_timeout_tokens:
                    # emby 查询超时，保留重试
                    failed_positions.append(r["index"])
                else:
                    logger.warning(f"无法找到 token 对应的用户名: {token}")
                    acknowledged_count += 1
                    skipped_count += 1
                continue

            # 使用内存缓存查询 user_id，避免数据库查询
            if service == "plex":
                user_id = plex_username_to_id.get(username.lower())
            else:
                user_id = emby_username_to_id.get(username.lower())

            event_hash = traffic_rules.build_event_hash(
                line=r["line"],
                service=service,
                username=username,
                user_id=user_id,
                timestamp=r["formatted_timestamp"],
                request_uri=r["decoded_uri"],
                send_bytes=r["bytes_sent"],
                upstream=r["upstream"],
                upstream_response_time=r["upstream_response_time"],
            )
            row = {
                "line": r["line"],
                "send_bytes": r["bytes_sent"],
                "service": service,
                "username": username,
                "user_id": user_id,
                "timestamp": r["formatted_timestamp"],
                "event_hash": event_hash,
                "request_uri": r["decoded_uri"],
                "upstream": r["upstream"],
                "upstream_response_time": r["upstream_response_time"],
            }
            to_insert.append((r["index"], row, event_hash))

        # 阶段3：批量写库并回填每条结果
        if to_insert:
            hash_status = traffic_service.store_traffic_batch(
                [row for _, row, _ in to_insert]
            )
            # 批内同一 event_hash 多条：首条按状态计数，其余计为重复，
            # 避免重复计入 processed（实际只入库一条）
            seen_hashes = set()
            for index, row, event_hash in to_insert:
                status = hash_status.get(event_hash, "failed")
                if status == "inserted":
                    if event_hash in seen_hashes:
                        duplicate_count += 1
                    else:
                        processed_count += 1
                    acknowledged_count += 1
                elif status == "duplicate":
                    duplicate_count += 1
                    acknowledged_count += 1
                else:
                    logger.error(
                        f"流量日志入库失败，将保留在处理中队列重试: event_hash={event_hash}"
                    )
                    failed_positions.append(index)
                seen_hashes.add(event_hash)

        if values:
            try:
                _finalize_processing_logs(
                    processed_log_count=len(values),
                    failed_positions=failed_positions,
                )
            except Exception as e:
                logger.error(f"批量确认处理完成的流量日志时发生错误: {e}")

        logger.info(
            f"流量日志处理完成: 本次转移 {transferred_count} 条, 成功新增 {processed_count} 条, 业务跳过 {skipped_count} 条, 重复跳过 {duplicate_count} 条, 已确认 {acknowledged_count} 条, 留待重试 {len(failed_positions)} 条"
        )

    except Exception as e:
        logger.error(f"更新线路流量统计时发生错误: {e}")
