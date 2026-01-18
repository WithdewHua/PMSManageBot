#!/usr/bin/env python3
"""
同步下载权限脚本

该脚本用于：
1. 获取 Plex/Emby 所有用户的下载权限状态
2. 如果媒体服务器上已开通下载权限，则更新到数据库
3. 检查 Premium 用户，为他们开通下载权限
"""

from time import time

from app.config import settings
from app.databases.session import get_session
from app.log import logger
from app.models.models import EmbyUser, PlexUser
from app.modules.emby import Emby
from app.modules.plex import Plex
from sqlalchemy import select


def get_plex_user_sync_status(plex: Plex, email: str) -> bool | None:
    """
    获取 Plex 用户的同步（下载）权限状态

    Args:
        plex: Plex 实例
        email: 用户邮箱

    Returns:
        bool: 是否允许同步，None 表示无法获取
    """
    try:
        user_info = plex.users_by_email.get(email)
        if not user_info:
            return None

        user_id, user = user_info

        # 管理员账户
        if email == settings.PLEX_ADMIN_EMAIL:
            return True

        # 获取用户在当前服务器的设置
        return user.allowSync
    except Exception as e:
        logger.error(f"获取 Plex 用户 {email} 同步权限失败: {e}")
        return None


def get_emby_user_download_status(emby: Emby, user_id: str) -> bool | None:
    """
    获取 Emby 用户的下载权限状态

    Args:
        emby: Emby 实例
        user_id: 用户 ID

    Returns:
        bool: 是否允许下载，None 表示无法获取
    """
    try:
        import requests

        headers = {"accept": "application/json"}
        params = {"api_key": emby.api_token}

        response = requests.get(
            url=emby.base_url + f"/Users/{user_id}", params=params, headers=headers
        )
        response.raise_for_status()
        policy = response.json().get("Policy", {})
        return policy.get("EnableContentDownloading", False)
    except Exception as e:
        logger.error(f"获取 Emby 用户 {user_id} 下载权限失败: {e}")
        return None


def sync_plex_download_permissions():
    """同步 Plex 用户的下载权限"""
    print("\n" + "=" * 60)
    print("开始同步 Plex 用户下载权限")
    print("=" * 60)

    plex = Plex()
    current_time = int(time())

    # 统计
    stats = {
        "total": 0,
        "already_unlocked_in_db": 0,
        "synced_from_plex": 0,
        "premium_enabled": 0,
        "errors": 0,
    }

    with get_session() as session:
        # 获取所有 Plex 用户
        stmt = select(PlexUser)
        plex_users = session.execute(stmt).scalars().all()

        for user in plex_users:
            stats["total"] += 1
            email = user.plex_email

            if not email:
                continue

            print(f"\n处理用户: {email}")

            # 1. 检查数据库中是否已解锁
            if user.sync_unlocked == 1:
                print("  ✓ 数据库中已标记为解锁")
                stats["already_unlocked_in_db"] += 1
                # 确保媒体服务器上也开通
                try:
                    plex.update_sync_for_user(email, allow_sync=True)
                except Exception as e:
                    print(f"  ✗ 更新 Plex 同步权限失败: {e}")
                continue

            # 2. 检查 Plex 上的权限状态
            plex_status = get_plex_user_sync_status(plex, email)
            if plex_status is True:
                print("  → Plex 上已开通同步权限，同步到数据库")
                user.sync_unlocked = 1
                user.sync_unlock_time = current_time
                stats["synced_from_plex"] += 1
                continue

            # 3. 检查是否为 Premium 用户
            if user.is_premium == 1:
                print("  → Premium 用户，开通下载权限（仅媒体服务器）")
                try:
                    plex.update_sync_for_user(email, allow_sync=True)
                    # 注意：不更新数据库字段，这样 Premium 过期后可以正确撤销权限
                    stats["premium_enabled"] += 1
                except Exception as e:
                    print(f"  ✗ 为 Premium 用户开通权限失败: {e}")
                    stats["errors"] += 1
                continue

            print("  - 未开通下载权限")

        session.commit()

    print("\n" + "-" * 60)
    print("Plex 同步完成:")
    print(f"  总用户数: {stats['total']}")
    print(f"  数据库已解锁: {stats['already_unlocked_in_db']}")
    print(f"  从 Plex 同步: {stats['synced_from_plex']}")
    print(f"  Premium 用户开通: {stats['premium_enabled']}")
    print(f"  错误数: {stats['errors']}")


def sync_emby_download_permissions():
    """同步 Emby 用户的下载权限"""
    print("\n" + "=" * 60)
    print("开始同步 Emby 用户下载权限")
    print("=" * 60)

    emby = Emby()
    current_time = int(time())

    # 统计
    stats = {
        "total": 0,
        "already_unlocked_in_db": 0,
        "synced_from_emby": 0,
        "premium_enabled": 0,
        "errors": 0,
    }

    with get_session() as session:
        # 获取所有 Emby 用户
        stmt = select(EmbyUser)
        emby_users = session.execute(stmt).scalars().all()

        for user in emby_users:
            stats["total"] += 1
            username = user.emby_username
            emby_id = user.emby_id

            print(f"\n处理用户: {username}")

            if not emby_id:
                print("  ✗ 无 Emby ID，跳过")
                continue

            # 1. 检查数据库中是否已解锁
            if user.download_unlocked == 1:
                print("  ✓ 数据库中已标记为解锁")
                stats["already_unlocked_in_db"] += 1
                # 确保媒体服务器上也开通
                try:
                    emby.update_download_permission_for_user(
                        emby_id, allow_download=True
                    )
                except Exception as e:
                    print(f"  ✗ 更新 Emby 下载权限失败: {e}")
                continue

            # 2. 检查 Emby 上的权限状态
            emby_status = get_emby_user_download_status(emby, emby_id)
            if emby_status is True:
                print("  → Emby 上已开通下载权限，同步到数据库")
                user.download_unlocked = 1
                user.download_unlock_time = current_time
                stats["synced_from_emby"] += 1
                continue

            # 3. 检查是否为 Premium 用户
            if user.is_premium == 1:
                print("  → Premium 用户，开通下载权限（仅媒体服务器）")
                try:
                    success, msg = emby.update_download_permission_for_user(
                        emby_id, allow_download=True
                    )
                    if success:
                        # 注意：不更新数据库字段，这样 Premium 过期后可以正确撤销权限
                        stats["premium_enabled"] += 1
                    else:
                        print(f"  ✗ 开通失败: {msg}")
                        stats["errors"] += 1
                except Exception as e:
                    print(f"  ✗ 为 Premium 用户开通权限失败: {e}")
                    stats["errors"] += 1
                continue

            print("  - 未开通下载权限")

        session.commit()

    print("\n" + "-" * 60)
    print("Emby 同步完成:")
    print(f"  总用户数: {stats['total']}")
    print(f"  数据库已解锁: {stats['already_unlocked_in_db']}")
    print(f"  从 Emby 同步: {stats['synced_from_emby']}")
    print(f"  Premium 用户开通: {stats['premium_enabled']}")
    print(f"  错误数: {stats['errors']}")


def main():
    print("=" * 60)
    print("下载权限同步脚本")
    print("=" * 60)
    print("\n该脚本将执行以下操作:")
    print("1. 检查媒体服务器上已开通下载权限的用户，同步到数据库")
    print("2. 为 Premium 用户在媒体服务器上开通下载权限（不更新数据库）")
    print("\n")

    # 选择同步服务
    print("请选择要同步的服务:")
    print("  1. 仅 Plex")
    print("  2. 仅 Emby")
    print("  3. 全部 (Plex + Emby)")
    print("  0. 退出")

    try:
        choice = input("\n请输入选项 (默认 3): ").strip() or "3"
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")
        return

    if choice == "0":
        print("已退出")
        return
    elif choice == "1":
        sync_plex_download_permissions()
    elif choice == "2":
        sync_emby_download_permissions()
    elif choice == "3":
        sync_plex_download_permissions()
        sync_emby_download_permissions()
    else:
        print("无效选项")
        return

    print("\n" + "=" * 60)
    print("同步完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
