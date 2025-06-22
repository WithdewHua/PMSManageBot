import json
import re
import secrets
import time

from app.cache import lucky_wheel_config_cache
from app.db import DB
from app.log import logger
from app.premium import update_premium_status
from app.update_db import add_redeem_code
from app.utils import get_user_name_from_tg_id
from app.webapp.auth import get_telegram_user
from app.webapp.middlewares import require_telegram_auth
from app.webapp.routers.admin import check_admin_permission
from app.webapp.schemas import TelegramUser
from app.webapp.schemas.luckywheel import (
    LuckyWheelConfig,
    LuckyWheelConfigUpdateRequest,
    LuckyWheelItem,
    LuckyWheelSpinResult,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/luckywheel", tags=["幸运大转盘"])

# 默认转盘配置
DEFAULT_WHEEL_CONFIG = LuckyWheelConfig(
    items=[
        LuckyWheelItem(name="谢谢参与", probability=15.0),
        LuckyWheelItem(name="积分 +10", probability=25.0),
        LuckyWheelItem(name="积分 -10", probability=20.0),
        LuckyWheelItem(name="积分 +30", probability=15.0),
        LuckyWheelItem(name="积分 -30", probability=10.0),
        LuckyWheelItem(name="邀请码 1 枚", probability=0.3),
        LuckyWheelItem(name="积分 +50", probability=7),
        LuckyWheelItem(name="积分 -50", probability=6),
        LuckyWheelItem(name="积分翻倍", probability=1),
        LuckyWheelItem(name="积分减半", probability=0.7),
    ],
    cost_credits=10,
    min_credits_required=30,
)


# 随机性增强配置
class RandomnessConfig:
    """随机性配置类"""

    # 是否启用加权随机算法（对低概率奖品进行保护）
    USE_WEIGHTED_PROTECTION = True
    # 保护阈值：概率低于此值的奖品会获得额外保护
    PROTECTION_THRESHOLD = 2.0
    # 保护系数：用于调整低概率奖品的实际中奖率
    PROTECTION_FACTOR = 1.2
    # 是否启用时间种子混合
    USE_TIME_SEED_MIXING = True
    # 是否启用用户ID种子混合
    USE_USER_SEED_MIXING = True

    @classmethod
    def to_dict(cls) -> dict:
        """将配置转换为字典"""
        return {
            "use_weighted_protection": cls.USE_WEIGHTED_PROTECTION,
            "protection_threshold": cls.PROTECTION_THRESHOLD,
            "protection_factor": cls.PROTECTION_FACTOR,
            "use_time_seed_mixing": cls.USE_TIME_SEED_MIXING,
            "use_user_seed_mixing": cls.USE_USER_SEED_MIXING,
        }

    @classmethod
    def from_dict(cls, config_dict: dict):
        """从字典更新配置"""
        cls.USE_WEIGHTED_PROTECTION = config_dict.get(
            "use_weighted_protection", cls.USE_WEIGHTED_PROTECTION
        )
        cls.PROTECTION_THRESHOLD = config_dict.get(
            "protection_threshold", cls.PROTECTION_THRESHOLD
        )
        cls.PROTECTION_FACTOR = config_dict.get(
            "protection_factor", cls.PROTECTION_FACTOR
        )
        cls.USE_TIME_SEED_MIXING = config_dict.get(
            "use_time_seed_mixing", cls.USE_TIME_SEED_MIXING
        )
        cls.USE_USER_SEED_MIXING = config_dict.get(
            "use_user_seed_mixing", cls.USE_USER_SEED_MIXING
        )


def get_wheel_config() -> LuckyWheelConfig:
    """获取转盘配置"""
    try:
        config_str = lucky_wheel_config_cache.get("config")
        if config_str:
            config_dict = json.loads(config_str)
            return LuckyWheelConfig(**config_dict)
        else:
            # 如果没有配置，使用默认配置并保存到Redis
            save_wheel_config(DEFAULT_WHEEL_CONFIG)
            return DEFAULT_WHEEL_CONFIG
    except Exception as e:
        logger.error(f"获取转盘配置失败: {e}")
        return DEFAULT_WHEEL_CONFIG


def save_wheel_config(config: LuckyWheelConfig):
    """保存转盘配置到Redis"""
    try:
        config_json = config.model_dump_json()
        lucky_wheel_config_cache.put("config", config_json)
        logger.info("转盘配置已保存到Redis")
    except Exception as e:
        logger.error(f"保存转盘配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="保存配置失败"
        )


def calculate_credits_change(
    item_name: str,
    current_credits: float,
    tg_id: int = None,
    gen_privileged_code: bool = False,
) -> float:
    """
    根据奖品名称计算积分变化

    Args:
        item_name: 奖品名称
        current_credits: 当前积分
        tg_id: Telegram用户ID，用于生成邀请码
        gen_privileged_code: 是否生成特权邀请码

    Returns:
        积分变化值（正数表示增加，负数表示减少）
    """
    name = item_name.lower().strip()

    # 特殊奖品处理
    special_rewards = {
        "谢谢参与": 0,
        "翻倍": lambda: round(current_credits, 2),
        "减半": lambda: round(-(current_credits / 2), 2),
        "邀请码": lambda: _handle_invite_code(tg_id, gen_privileged_code),
    }

    # 检查特殊奖品
    for keyword, value in special_rewards.items():
        if keyword in name:
            return value() if callable(value) else value

    # premium
    if "premium" in name:
        return _handle_premium_reward(tg_id, name)

    # 使用正则表达式匹配积分变化
    credits_pattern = re.compile(r"([+-])(\d+)")
    match = credits_pattern.search(name)

    if match:
        sign, amount = match.groups()
        credits_value = int(amount)
        return credits_value if sign == "+" else -credits_value

    # 默认返回 0
    return 0


def _handle_premium_reward(tg_id: int, name: str) -> float:
    """处理 Premium 奖品"""
    try:
        days_match = re.search(r"(\d+)", name)
        if days_match:
            days = int(days_match.group(1))
            db = DB()
            try:
                new_expiry = update_premium_status(db, tg_id, "plex", days)
                logger.info(
                    f"用户 {tg_id} 的 Plex Premium 已更新，新的到期时间为 {new_expiry or '永久会员'}"
                )
            except NameError:
                pass
            try:
                new_expiry = update_premium_status(db, tg_id, "emby", days)
                logger.info(
                    f"用户 {tg_id} 的 Emby Premium 已更新，新的到期时间为 {new_expiry or '永久会员'}"
                )
            except NameError:
                pass
    except Exception as e:
        logger.error(f"更新 Premium 状态失败: {e}")
    else:
        db.con.commit()
    finally:
        db.close()
    return 0  # Premium 奖品不涉及积分变化


def _handle_invite_code(tg_id: int = None, gen_privileged_code: bool = False) -> float:
    """处理邀请码奖品"""
    if tg_id:
        try:
            add_redeem_code(tg_id, num=1, is_privileged=gen_privileged_code)
            logger.info(f"为用户 {tg_id} 生成了邀请码")
        except Exception as e:
            logger.error(f"为用户 {tg_id} 生成邀请码失败: {e}")
    return 0


@router.get("/config", response_model=LuckyWheelConfig)
async def get_config():
    """获取转盘配置"""
    try:
        config = get_wheel_config()
        return config
    except Exception as e:
        logger.error(f"获取转盘配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置失败"
        )


@router.put("/config")
@require_telegram_auth
async def update_config(
    request: Request,
    config_update_request: LuckyWheelConfigUpdateRequest,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新转盘配置（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 验证概率总和
        total_probability = sum(
            item.probability for item in config_update_request.items
        )
        if abs(total_probability - 100.0) > 0.01:  # 允许小的浮点数误差
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"奖品概率总和必须为 100%，当前为 {total_probability}%",
            )

        # 获取当前配置
        current_config = get_wheel_config()

        # 更新配置
        new_config = LuckyWheelConfig(
            items=config_update_request.items,
            cost_credits=config_update_request.cost_credits
            or current_config.cost_credits,
            min_credits_required=config_update_request.min_credits_required
            or current_config.min_credits_required,
            gen_privileged_code=config_update_request.gen_privileged_code,
        )

        # 保存配置
        save_wheel_config(new_config)

        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"message": "转盘配置更新成功"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新转盘配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置失败"
        )


@router.post("/spin", response_model=LuckyWheelSpinResult)
@require_telegram_auth
async def spin_wheel(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """转动转盘"""
    try:
        db = DB()
        user_id = current_user.id

        # 获取转盘配置
        config = get_wheel_config()

        # 获取用户当前积分
        flag, current_credits = db.get_user_credits(user_id)
        if not flag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=current_credits
            )

        # 检查积分是否足够
        if current_credits < config.min_credits_required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"积分不足，需要至少 {config.min_credits_required} 积分才能参与",
            )

        # 扣除参与费用
        new_credits = current_credits - config.cost_credits
        db.update_user_credits(credits=new_credits, tg_id=user_id)

        # 选择中奖奖品 - 使用增强版随机选择器
        winner = random_select_winner(config.items, user_id=user_id)

        # 如果中奖奖品是邀请码，判断是否需要生成特权邀请码
        gen_privileged_code = False
        if "邀请码" in winner.name and config.gen_privileged_code:
            gen_privileged_code = True
            # 生成后立马关闭生成特权邀请码
            config.gen_privileged_code = False
            save_wheel_config(config)

        # 更新奖励，计算积分变化
        credits_change = calculate_credits_change(
            winner.name,
            new_credits,
            tg_id=user_id,
            gen_privileged_code=gen_privileged_code,
        )

        # 更新用户积分
        final_credits = new_credits + credits_change
        if final_credits < 0:
            final_credits = 0  # 积分不能为负数

        db.update_user_credits(credits=final_credits, tg_id=user_id)

        # 记录转盘统计数据
        db.add_wheel_spin_record(user_id, winner.name, credits_change)

        logger.info(
            f"用户 {get_user_name_from_tg_id(user_id)} 转盘结果: {winner.name}, 积分变化: {credits_change}, 最终积分: {final_credits}"
        )

        return LuckyWheelSpinResult(
            item=winner, credits_change=credits_change, current_credits=final_credits
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"转盘操作失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="转盘操作失败"
        )
    finally:
        db.close()


@router.get("/user-status")
@require_telegram_auth
async def get_user_status(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户转盘参与状态"""
    try:
        db = DB()
        user_id = current_user.id

        # 获取转盘配置
        config = get_wheel_config()

        # 获取用户当前积分
        flag, current_credits = db.get_user_credits(user_id)
        if not flag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=current_credits
            )

        can_participate = current_credits >= config.min_credits_required

        return {
            "can_participate": can_participate,
            "current_credits": current_credits,
            "min_credits_required": config.min_credits_required,
            "cost_credits": config.cost_credits,
        }

    except Exception as e:
        logger.error(f"获取用户转盘状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取用户状态失败"
        )
    finally:
        db.close()


def get_randomness_config_from_redis() -> dict:
    """从Redis获取随机性配置"""
    try:
        config_str = lucky_wheel_config_cache.get("randomness_config")
        if config_str:
            config_dict = json.loads(config_str)
            # 更新类配置
            RandomnessConfig.from_dict(config_dict)
            return config_dict
        else:
            # 如果没有配置，使用默认配置并保存到Redis
            default_config = RandomnessConfig.to_dict()
            save_randomness_config(default_config)
            return default_config
    except Exception as e:
        logger.error(f"获取随机性配置失败: {e}")
        return RandomnessConfig.to_dict()


def save_randomness_config(config_dict: dict):
    """保存随机性配置到Redis"""
    try:
        # 验证配置参数的合理性
        if "protection_threshold" in config_dict:
            threshold = float(config_dict["protection_threshold"])
            if not (0 < threshold <= 50):
                raise ValueError("保护阈值必须在0-50之间")

        if "protection_factor" in config_dict:
            factor = float(config_dict["protection_factor"])
            if not (1.0 <= factor <= 3.0):
                raise ValueError("保护系数必须在1.0-3.0之间")

        # 更新类配置
        RandomnessConfig.from_dict(config_dict)

        # 保存到Redis
        config_json = json.dumps(config_dict)
        lucky_wheel_config_cache.put("randomness_config", config_json)
        logger.info("随机性配置已保存到Redis")
    except Exception as e:
        logger.error(f"保存随机性配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存随机性配置失败",
        )


def random_select_winner(
    items: list[LuckyWheelItem], user_id: int = None
) -> LuckyWheelItem:
    """
    增强版随机选择器，提供更好的随机性和公平性

    Args:
        items: 奖品列表
        user_id: 用户ID，用于增强随机性

    Returns:
        选中的奖品
    """
    if not items:
        raise ValueError("奖品列表不能为空")

    # 从Redis加载最新配置
    get_randomness_config_from_redis()

    # 过滤有效奖品
    valid_items = [item for item in items if item.probability > 0]
    if not valid_items:
        raise ValueError("没有有效的奖品（概率必须大于0）")

    # 创建增强的随机数生成器
    secure_random = secrets.SystemRandom()

    # 如果启用了时间种子混合，使用当前时间的纳秒数作为额外熵源
    if RandomnessConfig.USE_TIME_SEED_MIXING:
        import time

        time_entropy = int(time.time_ns() % 1000000)
        # 使用时间熵影响随机种子
        secure_random.seed(time_entropy)

    # 计算调整后的概率（保护低概率奖品）
    adjusted_items = []
    if RandomnessConfig.USE_WEIGHTED_PROTECTION:
        for item in valid_items:
            adjusted_prob = item.probability
            # 对低概率奖品进行保护
            if item.probability < RandomnessConfig.PROTECTION_THRESHOLD:
                adjusted_prob *= RandomnessConfig.PROTECTION_FACTOR
            adjusted_items.append((item, adjusted_prob))
    else:
        adjusted_items = [(item, item.probability) for item in valid_items]

    # 计算总概率
    total_probability = sum(prob for _, prob in adjusted_items)

    # 生成随机数
    if RandomnessConfig.USE_USER_SEED_MIXING and user_id:
        # 使用用户ID增强随机性
        user_entropy = (
            hash(str(user_id) + str(secure_random.randint(1, 1000000))) % 1000000
        )
        random_value = (
            secure_random.uniform(0, total_probability) + user_entropy / 1000000
        ) % total_probability
    else:
        random_value = secure_random.uniform(0, total_probability)

    # 选择获奖奖品
    accumulated_probability = 0.0
    for item, adjusted_prob in adjusted_items:
        accumulated_probability += adjusted_prob
        if random_value < accumulated_probability:
            return item

    # 保护措施
    return adjusted_items[-1][0]


def get_randomness_stats(items: list[LuckyWheelItem], iterations: int = 10000) -> dict:
    """
    获取随机性统计信息，用于测试和验证随机算法的公平性

    Args:
        items: 奖品列表
        iterations: 测试迭代次数

    Returns:
        包含统计信息的字典
    """
    if not items or iterations <= 0:
        return {}

    # 统计每个奖品的中奖次数
    win_counts = {item.name: 0 for item in items}

    for _ in range(iterations):
        try:
            winner = random_select_winner(items)
            win_counts[winner.name] += 1
        except Exception:
            continue

    # 计算实际中奖率和期望中奖率
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
                "is_fair": deviation < 1.0,  # 偏差小于1%认为是公平的
            }

    return stats


@router.get("/randomness-stats")
@require_telegram_auth
async def get_randomness_statistics(
    request: Request,
    iterations: int = 10000,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """获取随机性统计信息（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 获取当前配置
        config = get_wheel_config()

        # 从Redis获取随机性配置
        randomness_config = get_randomness_config_from_redis()

        # 生成统计信息
        stats = get_randomness_stats(config.items, iterations)

        # 计算平均偏差
        deviations = [stat["deviation"] for stat in stats.values()]
        average_deviation = (
            round(sum(deviations) / len(deviations), 2) if deviations else 0
        )

        # 判断整体公平性
        overall_fairness = all(stat["is_fair"] for stat in stats.values())

        return {
            "iterations": iterations,
            "total_items": len(config.items),
            "valid_items": len([item for item in config.items if item.probability > 0]),
            "average_deviation": average_deviation,
            "overall_fairness": overall_fairness,
            "stats": stats,
            "config": randomness_config,
            "timestamp": str(int(time.time() * 1000)),  # 添加时间戳
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取随机性统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计信息失败"
        )


@router.put("/randomness-config")
@require_telegram_auth
async def update_randomness_config(
    request: Request,
    config_data: dict,
    current_user: TelegramUser = Depends(get_telegram_user),
):
    """更新随机性配置（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 获取当前配置
        current_config = get_randomness_config_from_redis()

        # 更新配置，保留未指定的字段
        updated_config = current_config.copy()
        updated_config.update(config_data)

        # 保存配置到Redis（包含验证）
        save_randomness_config(updated_config)

        logger.info(
            f"管理员 {get_user_name_from_tg_id(current_user.id)} 更新了随机性配置: {config_data}"
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"message": "随机性配置更新成功"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新随机性配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="更新配置失败"
        )


@router.get("/randomness-config")
@require_telegram_auth
async def get_randomness_config(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取当前随机性配置（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        # 从Redis获取配置
        config = get_randomness_config_from_redis()

        return config

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取随机性配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取配置失败"
        )


@router.get("/stats")
@require_telegram_auth
async def get_wheel_statistics(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取转盘统计数据（仅管理员）"""
    try:
        # 检查管理员权限
        check_admin_permission(current_user)

        db = DB()
        stats = db.get_wheel_stats()

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取转盘统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="获取统计数据失败"
        )
    finally:
        if "db" in locals():
            db.close()


@router.get("/user-activity-stats")
@require_telegram_auth
async def get_user_activity_stats(
    request: Request, current_user: TelegramUser = Depends(get_telegram_user)
):
    """获取用户个人活动统计数据"""
    try:
        db = DB()
        user_id = current_user.id

        # 获取用户转盘统计数据
        stats = db.get_user_wheel_stats(user_id)

        return {"success": True, "data": stats}

    except Exception as e:
        logger.error(f"获取用户活动统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户活动统计失败",
        )
    finally:
        db.close()
