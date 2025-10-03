import asyncio
import json
import math
import re
from datetime import datetime, timedelta
from time import time
from typing import Optional
from urllib.parse import parse_qs, urlparse
from uuid import NAMESPACE_URL, uuid3

from app.config import settings
from app.databases.cache import (
    emby_api_key_cache,
    plex_token_cache,
    stream_traffic_cache,
    user_credits_cache,
    user_info_cache,
)
from app.databases.db import DB
from app.log import logger
from app.modules.emby import Emby
from app.modules.plex import Plex
from app.modules.tautulli import Tautulli
from app.utils.utils import (
    get_user_name_from_tg_id,
    get_user_total_duration,
    send_message_by_url,
)


def update_plex_credits():
    """更新积分及观看时长"""
    logger.info("开始更新 Plex 用户积分及观看时长")
    _db = DB()
    notification_tasks = []
    try:
        # 获取一天内的观看时长
        duration = get_user_total_duration(
            Tautulli().get_home_stats(
                1, "duration", len(Plex().users_by_id), "top_users"
            )
        )
        # update credits and watched_time
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            play_duration = round(min(float(duration.get(plex_id, 0)), 24), 2)
            if play_duration == 0:
                continue
            # 最大记 8h
            credits_inc = min(play_duration, 8)
            res = _db.cur.execute(
                "SELECT credits,watched_time,tg_id,plex_username,is_premium FROM user WHERE plex_id=?",
                (plex_id,),
            ).fetchone()
            if not res:
                continue
            watched_time_init = res[1]
            tg_id = res[2]
            plex_username = res[3]
            is_premium = res[4]
            # 获取用户昨日的流量使用情况
            traffic_usage = _db.get_user_daily_traffic(
                plex_username,
                "plex",
                date=datetime.now(settings.TZ) - timedelta(days=1),
                premium_only=True,
            )
            traffic_usage_exceed = traffic_usage - (
                settings.USER_TRAFFIC_LIMIT
                if not is_premium
                else settings.PREMIUM_USER_TRAFFIC_LIMIT
            )
            traffic_cost_credits = 0
            if traffic_usage_exceed > 0:
                # 按10GB档位计费，不足10GB按10GB计算
                gb_tiers = math.ceil(traffic_usage_exceed / (10 * 1024 * 1024 * 1024))
                traffic_cost_credits = round(
                    gb_tiers * settings.CREDITS_COST_PER_10GB,
                    2,
                )
            if not tg_id:
                credits_init = res[0]
                credits = credits_init + credits_inc - traffic_cost_credits
                watched_time = watched_time_init + play_duration
                _db.cur.execute(
                    "UPDATE user SET credits=?,watched_time=? WHERE plex_id=?",
                    (credits, watched_time, plex_id),
                )
            else:
                credits_init = _db.cur.execute(
                    "SELECT credits FROM statistics WHERE tg_id=?", (tg_id,)
                ).fetchone()[0]
                credits = credits_init + credits_inc - traffic_cost_credits
                watched_time = watched_time_init + play_duration
                _db.cur.execute(
                    "UPDATE user SET watched_time=? WHERE plex_id=?",
                    (watched_time, plex_id),
                )
                _db.cur.execute(
                    "UPDATE statistics SET credits=? WHERE tg_id=?", (credits, tg_id)
                )
                if play_duration > 0:
                    # 需要发送通知
                    notification_tasks.append(
                        (
                            tg_id,
                            f"""
Plex 观看积分更新通知
====================

新增观看时长: {round(play_duration, 2)} 小时
新增观看积分：{round(credits_inc, 2)}
Premium 流量使用情况：{round(traffic_usage / (1024 * 1024 * 1024), 2)} GB
超出每日流量限额：{max(round(traffic_usage_exceed / (1024 * 1024 * 1024), 2), 0)} GB
流量消耗积分：{round(traffic_cost_credits, 2)}

积分变化：{round(credits_inc - traffic_cost_credits, 2)}

--------------------

当前总积分：{round(credits, 2)}
当前总观看时长：{round(watched_time, 2)} 小时

====================""",
                        )
                    )

            logger.info(
                f"更新 Plex 用户 {plex_username} ({plex_id}) 的积分和观看时长: "
                f"新增观看时长 {round(play_duration, 2)} 小时，新增观看积分 {round(credits_inc, 2)}, 流量消耗积分 {round(traffic_cost_credits, 2)}"
            )

    except Exception as e:
        logger.error(f"更新 Plex 用户积分及观看时长失败: {e}")
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append(
                (
                    chat_id,
                    f"更新 Plex 用户积分及观看时长失败: {e}",
                )
            )
        return notification_tasks
    else:
        _db.con.commit()
        logger.info("Plex 用户积分及观看时长更新完成")
        return notification_tasks
    finally:
        _db.close()


def update_emby_credits():
    """更新 emby 积分及观看时长"""
    logger.info("开始更新 Emby 用户积分及观看时长")
    # 获取所有用户的观看时长
    emby = Emby()
    _db = DB()
    notification_tasks = []
    try:
        duration = emby.get_user_total_play_time()
        # 获取数据库中的观看时长信息
        users = _db.cur.execute(
            "select emby_id, tg_id, emby_watched_time, emby_credits, emby_username, is_premium from emby_user"
        ).fetchall()
        for user in users:
            playduration = round(float(duration.get(user[0], 0)) / 3600, 2)
            if playduration == 0:
                continue
            # 最大记 8
            credits_inc = min(playduration - user[2], 8)
            emby_username, is_premium = user[4], user[5]
            # 获取用户昨日的流量使用情况
            traffic_usage = _db.get_user_daily_traffic(
                emby_username,
                "emby",
                date=datetime.now(settings.TZ) - timedelta(days=1),
                premium_only=True,
            )
            traffic_usage_exceed = traffic_usage - (
                settings.USER_TRAFFIC_LIMIT
                if not is_premium
                else settings.PREMIUM_USER_TRAFFIC_LIMIT
            )
            traffic_cost_credits = 0
            if traffic_usage_exceed > 0:
                # 按10GB档位计费，不足10GB按10GB计算
                gb_tiers = math.ceil(traffic_usage_exceed / (10 * 1024 * 1024 * 1024))
                traffic_cost_credits = round(
                    gb_tiers * settings.CREDITS_COST_PER_10GB,
                    2,
                )

            if not user[1]:
                _credits = user[3] + credits_inc - traffic_cost_credits
                _db.cur.execute(
                    "UPDATE emby_user SET emby_watched_time=?,emby_credits=? WHERE emby_id=?",
                    (playduration, _credits, user[0]),
                )
            else:
                stats_info = _db.get_stats_by_tg_id(user[1])
                # statistics 表中有数据
                if stats_info:
                    credits_init = stats_info[2]
                    _credits = credits_init + credits_inc - traffic_cost_credits
                    _db.update_user_credits(_credits, tg_id=user[1])
                else:
                    # 清空 emby_user 表中积分信息
                    _db.update_user_credits(0, emby_id=user[0])
                    # 在 statistic 表中增加用户数据
                    _credits = user[3] + credits_inc - traffic_cost_credits
                    _db.add_user_data(user[1], credits=_credits)
                # 更新 emby_user 表中观看时间
                _db.cur.execute(
                    "UPDATE emby_user SET emby_watched_time=? WHERE emby_id=?",
                    (playduration, user[0]),
                )
                if (playduration - user[2]) > 0:
                    # 需要发送消息通知
                    notification_tasks.append(
                        (
                            user[1],
                            f"""
Emby 观看积分更新通知
====================

新增观看时长: {round(playduration - user[2], 2)} 小时
新增观看积分：{round(credits_inc, 2)}
Premium 流量使用情况：{round(traffic_usage / (1024 * 1024 * 1024), 2)} GB
超出每日流量限额：{max(round(traffic_usage_exceed / (1024 * 1024 * 1024), 2), 0)} GB
流量消耗积分：{round(traffic_cost_credits, 2)}

积分变化：{round(credits_inc - traffic_cost_credits, 2)}

--------------------

当前总积分：{round(_credits, 2)}
当前总观看时长：{round(playduration, 2)} 小时

====================""",
                        )
                    )

            logger.info(
                f"更新 Emby 用户 {emby_username} ({user[0]}) 的积分和观看时长: "
                f"新增观看时长 {round(playduration - user[2], 2)} 小时，新增观看积分 {round(credits_inc, 2)}, 流量消耗积分 {round(traffic_cost_credits, 2)}"
            )
    except Exception as e:
        logger.error(f"更新 Emby 用户积分及观看时长失败: {e}")
        for chat_id in settings.TG_ADMIN_CHAT_ID:
            notification_tasks.append(
                (
                    chat_id,
                    f"更新 Emby 用户积分及观看时长失败: {e}",
                )
            )
        return notification_tasks
    else:
        _db.con.commit()
        logger.info("Emby 用户积分及观看时长更新完成")
        return notification_tasks
    finally:
        _db.close()


async def update_credits():
    """更新 Plex 和 Emby 用户积分及观看时长"""
    notification_tasks = update_plex_credits()
    notification_tasks.extend(update_emby_credits())
    for tg_id, text in notification_tasks:
        # 发送通知消息，静默模式
        await send_message_by_url(chat_id=tg_id, text=text, disable_notification=True)
        await asyncio.sleep(1)


def update_plex_info(
    plex_name=True, plex_id=True, plex_avatar=True, target_email: Optional[str] = None
):
    """更新 plex 用户信息"""
    _db = DB()
    _plex = Plex()
    try:
        if plex_name:
            users = _plex.users_by_id
            for uid, user in users.items():
                email = user[1].email
                username = user[0]
                _db.cur.execute(
                    "UPDATE user SET plex_username=?,plex_email=? WHERE plex_id=?",
                    (username, email, uid),
                )
        if plex_id:
            # 检查是否存在 plex_id 为空的用户
            if target_email:
                # 如果指定了目标邮箱，只处理该邮箱
                empty_plex_users = _db.cur.execute(
                    "SELECT plex_email FROM user WHERE plex_id IS NULL AND plex_email=?",
                    (target_email,),
                ).fetchall()
            else:
                # 处理所有 plex_id 为空的用户
                empty_plex_users = _db.cur.execute(
                    "SELECT plex_email FROM user WHERE plex_id IS NULL"
                ).fetchall()

            for user in empty_plex_users:
                email = user[0]
                # 处理 plex_id 为空的用户
                plex_id = _plex.get_user_id_by_email(email)
                plex_username = (
                    _plex.get_username_by_user_id(plex_id) if plex_id else None
                )
                if plex_id and plex_username:
                    _db.cur.execute(
                        "UPDATE user SET plex_id=?, plex_username=? WHERE plex_email=?",
                        (plex_id, plex_username, email),
                    )
                    logger.info(f"成功更新 Plex 用户 {email} 的 plex_id: {plex_id}")

                    # 如果是针对特定邮箱的调度任务，且成功获取到 plex_id，则标记任务待删除
                    if target_email and email.lower() == target_email.lower():
                        # 使用延迟删除，避免在任务执行过程中删除自己
                        import threading

                        def delayed_job_removal():
                            try:
                                import time

                                # 等待当前任务执行完成
                                time.sleep(2)
                                from app.scheduler import Scheduler

                                scheduler = Scheduler()
                                job_id = f"update_plex_info_for_{target_email}"
                                scheduler.remove_job(job_id)
                                logger.info(f"成功删除调度任务: {job_id}")
                            except Exception as e:
                                logger.warning(f"延迟删除调度任务失败: {e}")

                        # 在新线程中执行删除操作
                        threading.Thread(
                            target=delayed_job_removal, daemon=True
                        ).start()
                        logger.info(
                            f"已标记删除调度任务: update_plex_info_for_{target_email}"
                        )
                else:
                    logger.warning(
                        f"无法找到 Plex 用户 {email} 的 ID 或用户名，跳过更新。"
                    )
        # 更新所有用户的头像
        if plex_avatar:
            _plex.update_all_user_avatars()
    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def update_all_lib():
    """更新用户资料库权限状态"""
    _db = DB()
    _plex = Plex()
    try:
        users = _plex.users_by_email
        all_libs = _plex.get_libraries()
        for email, user in users.items():
            if not email:
                continue
            _info = _db.cur.execute("select * from user where plex_email=?", (email,))
            _info = _info.fetchone()
            if not _info:
                continue
            cur_libs = _plex.get_user_shared_libs_by_id(user[0])
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            _db.cur.execute(
                "UPDATE user SET all_lib=? WHERE plex_email=?", (all_lib_flag, email)
            )
    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def update_watched_time():
    """更新用户观看时长"""
    duration = get_user_total_duration(
        Tautulli().get_home_stats(
            36500, "duration", len(Plex().users_by_id), "top_users"
        )
    )
    _db = DB()
    try:
        res = _db.cur.execute("select plex_id from user")
        users = res.fetchall()
        for user in users:
            plex_id = user[0]
            watched_time = duration.get(plex_id, 0)
            _db.cur.execute(
                "UPDATE user SET watched_time=? WHERE plex_id=?",
                (watched_time, plex_id),
            )

    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def add_all_plex_user():
    """将所有 plex 用户均加入到数据库中"""

    duration = get_user_total_duration(
        Tautulli().get_home_stats(
            36500, "duration", len(Plex().users_by_id), "top_users"
        )
    )
    _plex = Plex()
    users = [user for user in _plex.my_plex_account.users()]
    users.append(_plex.my_plex_account)
    _db = DB()
    all_libs = Plex().get_libraries()
    try:
        _existing_users = _db.cur.execute("select plex_id from user").fetchall()
        existing_users = [user[0] for user in _existing_users]
        for user in users:
            # 已存在用户及未接受邀请用户跳过
            if user.id in existing_users or (not user.email):
                continue
            watched_time = duration.get(user.id, 0)
            try:
                cur_libs = _plex.get_user_shared_libs_by_id(user.id)
            # 跳过分享给我的用户
            except Exception as e:
                print(e)
                continue
            all_lib_flag = 1 if not set(all_libs).difference(set(cur_libs)) else 0
            _db.add_plex_user(
                plex_id=user.id,
                tg_id=None,
                plex_email=user.email,
                plex_username=user.username,
                credits=watched_time,
                all_lib=all_lib_flag,
                watched_time=watched_time,
            )

    except Exception as e:
        print(e)
    else:
        _db.con.commit()
    finally:
        _db.close()


def update_donation_credits(old_multiplier, new_multiplier):
    """
    更新捐赠积分

    Args:
        old_multiplier: 旧的积分倍数
        new_multiplier: 新的积分倍数
    """
    try:
        db = DB()
        # 获取所有捐赠记录
        donations = db.cur.execute(
            "SELECT tg_id, donation, credits FROM statistics WHERE donation > 0"
        ).fetchall()

        for tg_id, donation, credits in donations:
            # 计算新的积分
            new_credits = round(
                credits + donation * (new_multiplier - old_multiplier), 2
            )
            # 更新数据库
            db.cur.execute(
                "UPDATE statistics SET credits = ? WHERE tg_id = ?",
                (new_credits, tg_id),
            )
            logger.info(
                f"用户 {tg_id} 捐赠：{donation}, 更新积分: {credits} -> {new_credits}"
            )

        db.con.commit()
    except Exception as e:
        logger.error(str(e))
    finally:
        db.close()


def add_redeem_code(tg_id=None, num=1, is_privileged=False):
    """
    生成邀请码

    Args:
        tg_id: 用户ID，None表示为所有用户生成
        num: 生成数量
        is_privileged: 是否生成特权邀请码
    """
    from app.config import settings

    db = DB()
    if tg_id is None:
        tg_id = [
            u[0] for u in db.cur.execute("SELECT tg_id FROM statistics").fetchall()
        ]
    elif not isinstance(tg_id, list):
        tg_id = [tg_id]
    try:
        for uid in tg_id:
            for _ in range(num):
                code = uuid3(NAMESPACE_URL, str(uid + time())).hex
                db.add_invitation_code(code, owner=uid)

                # 如果是特权邀请码，添加到特权码列表
                if is_privileged:
                    if code not in settings.PRIVILEGED_CODES:
                        settings.PRIVILEGED_CODES.append(code)
                        # 保存到配置文件
                        settings.save_config_to_env_file(
                            {"PRIVILEGED_CODES": ",".join(settings.PRIVILEGED_CODES)}
                        )
                        logger.info(
                            f"添加特权邀请码 {code} 给用户 {get_user_name_from_tg_id(uid)}"
                        )
                else:
                    logger.info(
                        f"添加邀请码 {code} 给用户 {get_user_name_from_tg_id(uid)}"
                    )
    except Exception as e:
        print(e)
    else:
        db.con.commit()
    finally:
        db.close()


async def finish_expired_auctions_job():
    """定时任务：结束过期的竞拍活动"""
    try:
        db = DB()
        finished_auctions = db.finish_expired_auctions()
        # 通知用户
        for autction in finished_auctions:
            await send_message_by_url(
                autction.get("winner_id"),
                f"恭喜你，竞拍 {autction['title']} 获胜！最终出价为 {autction['final_price']} 积分",
            )
            if not autction.get("credits_reduced", False):
                # 如果未扣除积分，通知管理员
                for chat_id in settings.TG_ADMIN_CHAT_ID:
                    await send_message_by_url(
                        chat_id=chat_id,
                        text=f"用户 {autction.get('winner_id')} 在竞拍 {autction['title']} 中获胜，但未扣除积分。",
                    )
        return finished_auctions
    except Exception as e:
        logger.error(f"自动结束过期竞拍失败: {e}")
    finally:
        db.close()


async def monthly_traffic_data_migration():
    """定时任务：月度流量数据迁移聚合"""
    try:
        db = DB()

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
        success, message = db.aggregate_monthly_traffic_data(target_month)

        if success:
            logger.info(f"数据聚合成功: {message}")

            # 第二步：清理原始数据
            cleanup_success, cleanup_message = db.cleanup_monthly_traffic_data(
                target_month
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
    finally:
        db.close()


async def update_line_traffic_stats(
    count: int = settings.REDIS_LINE_TRAFFIC_STATS_HANDLE_SIZE,
):
    """
    更新线路的流量数据
    """

    # 每次从 redis 中取出指定数量的数据
    values = stream_traffic_cache.redis_client.lpop(
        "filebeat_nginx_stream_logs", count=count
    )

    if not values:
        logger.info("没有新的流量日志数据")
        return

    _db = DB()
    processed_count = 0

    try:
        for raw_log in values:
            try:
                # 解析 JSON 日志
                if isinstance(raw_log, bytes):
                    raw_log = raw_log.decode("utf-8")

                log_data = json.loads(raw_log)

                # 提取时间戳
                timestamp = log_data.get("@timestamp", "")

                # 提取后端服务器信息（线路）
                backend = log_data.get("backend", "")

                # 解析 message 字段中的 nginx 访问日志
                message = log_data.get("message", "")

                # 使用正则表达式解析 nginx 访问日志格式
                # 格式: IP - - [时间] "方法 URL 协议" 状态码 字节数 "引用"
                log_pattern = r"(\S+) - \S+? \[([^\]]+)\] \"(\S+) ([^\"]+) ([^\"]+)\" (\d+) (\d+) \"([^\"]*)\""
                match = re.match(log_pattern, message)

                if not match:
                    logger.warning(f"无法解析日志格式: {message}")
                    continue

                # 提取需要的字段
                access_time = match.group(2)
                url = match.group(4)
                status_code = int(match.group(6))
                bytes_sent = int(match.group(7))

                # 只处理成功的请求 (2xx 状态码)
                if status_code < 200 or status_code >= 300:
                    continue

                if not url.startswith("/stream") and not re.search(
                    r"[Oo]riginal\.|[Ss]tream\.?", url
                ):
                    # 只处理 /stream 路径的请求
                    # 或者包含 "Original." 的请求（兼容下 emby 反代）
                    logger.debug(f"跳过非流媒体请求: {url}")
                    continue

                # 解析 URL 获取服务信息
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)

                # 检查服务和 token
                service_list = query_params.get("service")
                token_list = query_params.get("token")
                line_list = query_params.get("line")
                if not service_list or not token_list:
                    if query_params.get("api_key"):
                        # 兼容 emby 反代
                        logger.warning(
                            f"缺少必要的参数 service 或 token，但发现 api_key: {url}"
                        )
                        service_list = ["emby"]
                        token_list = query_params.get("api_key")
                    else:
                        # 如果没有 service 或 token，跳过此条记录
                        logger.warning(f"缺少必要的参数 service 或 token: {url}")
                        continue

                service = service_list[0]
                token = token_list[0]
                # 优先使用 line 参数，如果没有则使用 backend
                # line 可能是自定义线路，仍会统计到，只是在线路流量统计中不会显示
                backend = line_list[0] if line_list else backend
                if not backend:
                    logger.warning(f"缺少 backend 信息: {url}")
                    continue

                username = None
                user_id = None

                if service == "plex":
                    username = plex_token_cache.get(token)
                    if username:
                        user_result = _db.cur.execute(
                            "SELECT plex_id FROM user WHERE LOWER(plex_username)=?",
                            (username.lower(),),
                        ).fetchone()
                        if user_result:
                            user_id = user_result[0]
                elif service == "emby":
                    username = emby_api_key_cache.get(token)
                    if username:
                        user_result = _db.cur.execute(
                            "SELECT emby_id FROM emby_user WHERE LOWER(emby_username)=?",
                            (username.lower(),),
                        ).fetchone()
                        if user_result:
                            user_id = user_result[0]
                    else:
                        # 尝试通过 api key 获取用户名
                        emby = Emby()
                        username = await emby.get_emby_username_from_api_key(token)

                # 如果无法获取到用户信息，跳过此条记录
                if not username:
                    logger.warning(f"无法找到 token 对应的用户名: {token}")
                    continue

                # 转换时间格式为 ISO 格式
                try:
                    # 将 nginx 时间格式转换为 datetime 对象
                    # 格式: 23/Jun/2025:15:43:03 +0000
                    dt = datetime.strptime(
                        access_time, "%d/%b/%Y:%H:%M:%S %z"
                    ).astimezone(settings.TZ)
                    formatted_timestamp = dt.isoformat()
                except ValueError:
                    # 如果解析失败，使用原始的 @timestamp
                    formatted_timestamp = (
                        datetime.fromisoformat(timestamp)
                        .astimezone(settings.TZ)
                        .isoformat()
                        if timestamp
                        else ""
                    )

                # 存储到数据库
                success = _db.create_line_traffic_entry(
                    line=backend,
                    send_bytes=bytes_sent,
                    service=service,
                    username=username,
                    user_id=user_id,
                    timestamp=formatted_timestamp,
                )

                if success:
                    logger.info(
                        f"成功处理日志: line={backend}, service={service}, user={username}, bytes={bytes_sent}, time={formatted_timestamp}"
                    )
                    processed_count += 1

            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析错误: {e}, 原始数据: {raw_log}")
                continue
            except Exception as e:
                logger.error(f"处理日志时发生错误: {e}, 原始数据: {raw_log}")
                continue

        logger.info(f"成功处理了 {processed_count} 条流量日志")

    except Exception as e:
        logger.error(f"更新线路流量统计时发生错误: {e}")
    finally:
        _db.close()


def rewrite_users_credits_to_redis():
    """
    将用户积分信息写入 redis 缓存
    """
    _db = DB()
    try:
        # 从 statistics 表中获取所有用户的积分信息
        stats = _db.cur.execute("SELECT tg_id, credits FROM statistics").fetchall()
        user_stats = {tg_id: credits for tg_id, credits in stats}
        # 获取 Plex 用户信息
        plex_users = _db.cur.execute(
            "SELECT plex_id, tg_id, credits, plex_username FROM user"
        ).fetchall()
        for user in plex_users:
            # 未接受邀请，此时数据库中的 plex_id 为空
            if not user[0]:
                continue
            tg_id = user[1]
            credits = user[2]
            plex_username = user[3]
            if tg_id:
                credits = user_stats.get(tg_id, 0)
            user_credits_cache.put(f"plex:{plex_username.lower()}", credits)
        # 获取 Emby 用户信息
        emby_users = _db.cur.execute(
            "SELECT emby_id, tg_id, emby_credits, emby_username FROM emby_user"
        ).fetchall()
        for user in emby_users:
            tg_id = user[1]
            credits = user[2]
            emby_username = user[3]
            if tg_id:
                credits = user_stats.get(tg_id, 0)
            user_credits_cache.put(f"emby:{emby_username.lower()}", credits)
    except Exception as e:
        logger.error(f"检查用户积分时发生错误: {e}")
    finally:
        _db.close()


def write_user_info_cache():
    """
    将 user info 写入 redis 缓存
    """
    _db = DB()
    try:
        # 获取 Plex 用户信息
        plex_users = _db.cur.execute(
            "SELECT plex_id, tg_id, plex_username, plex_email, is_premium FROM user"
        ).fetchall()
        for user in plex_users:
            plex_id = user[0]
            # 未接受邀请，此时数据库中的 plex_id 为空
            if not plex_id:
                continue
            tg_id = user[1]
            plex_username = user[2]
            plex_email = user[3]
            is_premium = user[4]
            if plex_username:
                user_info_cache.put(
                    f"plex:{plex_username.lower()}",
                    json.dumps(
                        {
                            "plex_id": plex_id,
                            "tg_id": tg_id,
                            "plex_username": plex_username,
                            "plex_email": plex_email,
                            "is_premium": is_premium,
                        }
                    ),
                )
        # 获取 Emby 用户信息
        emby_users = _db.cur.execute(
            "SELECT emby_id, tg_id, emby_username, is_premium FROM emby_user"
        ).fetchall()
        for user in emby_users:
            emby_id = user[0]
            tg_id = user[1]
            emby_username = user[2]
            is_premium = user[3]
            if emby_username:
                user_info_cache.put(
                    f"emby:{emby_username.lower()}",
                    json.dumps(
                        {
                            "emby_id": emby_id,
                            "tg_id": tg_id,
                            "emby_username": emby_username,
                            "is_premium": is_premium,
                        }
                    ),
                )
    except Exception as e:
        logger.error(f"写入用户信息缓存时发生错误: {e}")
    finally:
        _db.close()


async def check_expired_crypto_donation_orders():
    """定时任务：检查并更新过期的 crypto 捐赠订单状态"""
    try:
        logger.info("开始检查过期的 crypto 捐赠订单")

        db = DB()

        # 获取过期的订单（用于通知）
        expired_orders = db.get_expired_crypto_donation_orders()

        if not expired_orders:
            logger.info("没有找到过期的 crypto 捐赠订单")
            return

        # 更新过期订单状态
        updated_count = db.update_expired_crypto_donation_orders()

        if updated_count > 0:
            logger.info(f"成功更新 {updated_count} 个过期的 crypto 捐赠订单状态")

            # 准备通知消息
            notification_messages = []

            # 通知用户订单已过期
            for order in expired_orders:
                user_id = order["user_id"]
                order_id = order["order_id"]
                amount = order["amount"]
                crypto_type = order["crypto_type"]

                user_message = f"""
💰 Crypto 捐赠订单过期通知

订单号：{order_id}
金额：{amount:.2f} CNY
加密货币类型：{crypto_type}
状态：已过期

很抱歉，您的 Crypto 捐赠订单已超过有效期。如需继续捐赠，请重新创建订单。

感谢您对项目的支持！
"""

                notification_messages.append((user_id, user_message))

            # 通知管理员
            admin_message = f"""
📊 Crypto 捐赠订单过期统计

共处理过期订单：{updated_count} 个

详情：
"""
            for order in expired_orders:
                user_name = get_user_name_from_tg_id(order["user_id"])
                admin_message += f"• 用户：{user_name} ({order['user_id']}) - {order['amount']:.2f} CNY ({order['crypto_type']})\n"

            # 发送用户通知
            for user_id, message in notification_messages:
                try:
                    await send_message_by_url(
                        chat_id=user_id, text=message, disable_notification=True
                    )
                    await asyncio.sleep(0.5)  # 避免发送过于频繁
                except Exception as e:
                    logger.warning(f"向用户 {user_id} 发送过期订单通知失败: {e}")

            # 发送管理员通知
            for admin_chat_id in settings.TG_ADMIN_CHAT_ID:
                try:
                    await send_message_by_url(
                        chat_id=admin_chat_id,
                        text=admin_message,
                        disable_notification=True,
                    )
                except Exception as e:
                    logger.warning(
                        f"向管理员 {admin_chat_id} 发送过期订单统计失败: {e}"
                    )

        db.close()

    except Exception as e:
        logger.error(f"检查过期 crypto 捐赠订单失败: {e}")


if __name__ == "__main__":
    update_plex_credits()
    update_plex_info()
    # add_all_plex_user()
    update_emby_credits()
    # 测试流量统计更新
    # update_line_traffic_stats()
