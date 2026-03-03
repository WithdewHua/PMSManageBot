#!/usr/bin/env python3
"""
回填脚本：为数据库中已使用的邀请码补充 plex_id 和 emby_id 字段

处理逻辑：
- 跳过 used_by 以 "credits_by_" 开头的记录（积分兑换，无对应用户）
- 跳过未使用的邀请码（is_used == 0）
- 对 service == 'plex' 的记录：
    - 若 plex_id 已有值则跳过
    - 通过 plex_email（即 used_by）在 plex_user 表中查找 plex_id，并回填
    - 若找不到对应用户则打印警告，不处理
- 对 service == 'emby' 的记录：
    - 若 emby_id 已有值则跳过
    - 通过 emby_username（即 used_by）在 emby_user 表中查找 emby_id，并回填
    - 若找不到对应用户则打印警告，不处理
- 对 service 为 NULL 且不是积分兑换的记录，仅打印警告，不处理
"""

import os
import sys

# 将 src 目录加入 Python 路径，以便直接运行脚本
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.databases.db import db
from app.databases.session import get_session
from app.models.models import Invitation
from sqlalchemy import select, update


def backfill_invitation_ids():
    skipped_unused = 0
    skipped_credits = 0
    skipped_already_set = 0
    updated_plex = 0
    updated_emby = 0
    not_found_plex = []  # 在 plex_user 表中找不到对应用户
    not_found_emby = []  # 在 emby_user 表中找不到对应用户
    no_service = []  # service 为 NULL 且非积分兑换

    # 获取所有已使用的邀请码，在 session 关闭前提取所需字段
    with get_session() as session:
        stmt = select(Invitation).where(Invitation.is_used == 1)
        invitations = [
            {
                "code": inv.code,
                "used_by": inv.used_by,
                "service": inv.service,
                "plex_id": inv.plex_id,
                "emby_id": inv.emby_id,
            }
            for inv in session.execute(stmt).scalars().all()
        ]

    print(f"共找到 {len(invitations)} 条已使用的邀请码，开始处理...\n")

    for inv in invitations:
        code = inv["code"]
        used_by = inv["used_by"] or ""
        service = inv["service"]

        # 跳过积分兑换的记录（used_by 以 "credits_by_" 开头）
        if used_by.startswith("credits_by_"):
            skipped_credits += 1
            continue

        # 没有 service 信息的记录（非积分兑换），仅警告
        if not service:
            no_service.append((code, used_by))
            continue

        if service == "plex":
            # 已有 plex_id 则跳过
            if inv["plex_id"] is not None:
                skipped_already_set += 1
                continue

            # 通过 plex_email 查找 plex_id
            plex_info = db.get_plex_info_by_plex_email(used_by)
            if not plex_info:
                not_found_plex.append((code, used_by))
                continue

            # plex_info 为 tuple：(plex_id, tg_id, credits, plex_email, plex_username, ...)
            # plex_id 在索引 0
            plex_id = plex_info[0] if plex_info else None
            if not plex_id:
                not_found_plex.append((code, used_by))
                print(f"  [警告] Plex 用户 {used_by} 存在但 plex_id 为空，code={code}")
                continue

            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(Invitation.code == code)
                    .values(plex_id=plex_id)
                )
            updated_plex += 1
            print(
                f"  [已更新 plex_id] code={code}  plex_email={used_by}  plex_id={plex_id}"
            )

        elif service == "emby":
            # 已有 emby_id 则跳过
            if inv["emby_id"] is not None:
                skipped_already_set += 1
                continue

            # 通过 emby_username 查找 emby_id
            emby_info = db.get_emby_info_by_emby_username(used_by)
            if not emby_info:
                not_found_emby.append((code, used_by))
                continue

            # emby_info 为 tuple：(emby_username, emby_id, tg_id, ...)
            # emby_id 在索引 1
            emby_id = emby_info[1] if emby_info else None
            if not emby_id:
                not_found_emby.append((code, used_by))
                print(f"  [警告] Emby 用户 {used_by} 存在但 emby_id 为空，code={code}")
                continue

            with get_session() as session:
                session.execute(
                    update(Invitation)
                    .where(Invitation.code == code)
                    .values(emby_id=emby_id)
                )
            updated_emby += 1
            print(
                f"  [已更新 emby_id] code={code}  emby_username={used_by}  emby_id={emby_id}"
            )

    # 打印汇总
    print("\n" + "=" * 60)
    print("处理完成，汇总：")
    print(f"  跳过（未使用）              : {skipped_unused}")
    print(f"  跳过（积分兑换）            : {skipped_credits}")
    print(f"  跳过（已有 plex_id/emby_id）: {skipped_already_set}")
    print(f"  更新 plex_id                : {updated_plex}")
    print(f"  更新 emby_id                : {updated_emby}")
    print(f"  Plex 用户未找到（未处理）   : {len(not_found_plex)}")
    print(f"  Emby 用户未找到（未处理）   : {len(not_found_emby)}")
    print(f"  service 为空（未处理）      : {len(no_service)}")

    if not_found_plex:
        print("\n⚠️  以下 Plex 邀请码在 plex_user 表中找不到对应用户，请人工确认：")
        for code, used_by in not_found_plex:
            print(f"    code={code}  plex_email={used_by}")

    if not_found_emby:
        print("\n⚠️  以下 Emby 邀请码在 emby_user 表中找不到对应用户，请人工确认：")
        for code, used_by in not_found_emby:
            print(f"    code={code}  emby_username={used_by}")

    if no_service:
        print(
            "\n⚠️  以下已使用邀请码的 service 字段为空，无法判断服务类型，请人工确认："
        )
        print(
            "    （提示：可先运行 backfill_invitation_service.py 补全 service 字段后再重新运行本脚本）"
        )
        for code, used_by in no_service:
            print(f"    code={code}  used_by={used_by}")


if __name__ == "__main__":
    backfill_invitation_ids()
