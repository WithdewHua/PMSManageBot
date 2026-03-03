#!/usr/bin/env python3
"""
回填脚本：为数据库中已使用的邀请码补充 service 字段

处理逻辑：
- 跳过 used_by 以 "credits_by_" 开头的记录（积分兑换，无 service）
- 跳过已有 service 值的记录
- 在 plex_user 表中按邮箱查找（plex_email），匹配则设置 service = 'plex'
- 在 emby_user 表中按用户名查找（emby_username），匹配则设置 service = 'emby'
- 两个表都能匹配到：打印出来，不做处理
- 两个表都无法匹配：打印出来，不做处理
"""

from app.databases.db import db
from app.databases.session import get_session
from app.models.models import Invitation
from sqlalchemy import select, update


def backfill_invitation_service():
    skipped_credits = 0
    skipped_already_set = 0
    updated_plex = 0
    updated_emby = 0
    ambiguous = []  # 两个表都能匹配到
    unmatched = []  # 两个表都无法匹配

    # 获取所有已使用的邀请码，在 session 关闭前提取所需字段，避免 DetachedInstanceError
    with get_session() as session:
        stmt = select(Invitation).where(Invitation.is_used == 1)
        invitations = [
            {"code": inv.code, "used_by": inv.used_by, "service": inv.service}
            for inv in session.execute(stmt).scalars().all()
        ]

    print(f"共找到 {len(invitations)} 条已使用的邀请码，开始处理...\n")

    for inv in invitations:
        code = inv["code"]
        used_by = inv["used_by"] or ""

        # 跳过积分兑换的记录
        if used_by.startswith("credits_by_"):
            skipped_credits += 1
            continue

        # 跳过已有 service 的记录
        if inv["service"]:
            skipped_already_set += 1
            continue

        # 在 plex_user 表按 plex_email 查找
        in_plex = db.get_plex_info_by_plex_email(used_by) is not None

        # 在 emby_user 表按 emby_username 查找
        in_emby = db.get_emby_info_by_emby_username(used_by) is not None

        if in_plex and in_emby:
            ambiguous.append((code, used_by))
            continue

        if not in_plex and not in_emby:
            unmatched.append((code, used_by))
            continue

        service = "plex" if in_plex else "emby"

        # 更新 service 字段
        with get_session() as session:
            session.execute(
                update(Invitation)
                .where(Invitation.code == code)
                .values(service=service)
            )

        if in_plex:
            updated_plex += 1
        else:
            updated_emby += 1

        print(f"  [已更新] code={code}  used_by={used_by}  service={service}")

    # 打印汇总
    print("\n" + "=" * 60)
    print("处理完成，汇总：")
    print(f"  跳过（积分兑换）       : {skipped_credits}")
    print(f"  跳过（已有 service）   : {skipped_already_set}")
    print(f"  更新为 plex            : {updated_plex}")
    print(f"  更新为 emby            : {updated_emby}")
    print(f"  两表均匹配（未处理）   : {len(ambiguous)}")
    print(f"  两表均未匹配（未处理） : {len(unmatched)}")

    if ambiguous:
        print("\n⚠️  以下邀请码在 plex_user 和 emby_user 表中均能找到匹配，请人工确认：")
        for code, used_by in ambiguous:
            print(f"    code={code}  used_by={used_by}")

    if unmatched:
        print("\n⚠️  以下邀请码在 plex_user 和 emby_user 表中均无匹配，请人工确认：")
        for code, used_by in unmatched:
            print(f"    code={code}  used_by={used_by}")


if __name__ == "__main__":
    backfill_invitation_service()
