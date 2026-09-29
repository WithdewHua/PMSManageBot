"""
回填脚本：为数据库中已使用的邀请码补充 service 字段。

默认只修改能唯一匹配到 Plex 或 Emby 账户的记录；积分兑换记录、已有 service
记录、两边都匹配或都不匹配的记录都会保留给人工复核。
"""

from app.domains.identity import service as identity_service
from app.domains.invitation import repository as invitation_repository


def backfill_invitation_service() -> None:
    skipped_credits = 0
    skipped_already_set = 0
    updated_plex = 0
    updated_emby = 0
    ambiguous: list[tuple[str, str]] = []
    unmatched: list[tuple[str, str]] = []

    invitations = invitation_repository.list_used_invitation_records()
    print(f"共找到 {len(invitations)} 条已使用的邀请码，开始处理...\n")

    for invitation in invitations:
        code = str(invitation["code"])
        used_by = str(invitation["used_by"] or "")
        if used_by.startswith("credits_by_"):
            skipped_credits += 1
            continue
        if invitation["service"]:
            skipped_already_set += 1
            continue

        in_plex = identity_service.find_plex_by_email(used_by) is not None
        in_emby = identity_service.find_emby_by_username(used_by) is not None
        if in_plex and in_emby:
            ambiguous.append((code, used_by))
            continue
        if not in_plex and not in_emby:
            unmatched.append((code, used_by))
            continue

        service = "plex" if in_plex else "emby"
        invitation_repository.update_invitation_service(code, service)
        if in_plex:
            updated_plex += 1
        else:
            updated_emby += 1
        print(f"  [已更新] code={code}  used_by={used_by}  service={service}")

    print("\n" + "=" * 60)
    print("处理完成，汇总：")
    print(f"  跳过（积分兑换）       : {skipped_credits}")
    print(f"  跳过（已有 service）   : {skipped_already_set}")
    print(f"  更新为 plex            : {updated_plex}")
    print(f"  更新为 emby            : {updated_emby}")
    print(f"  两表均匹配（未处理）   : {len(ambiguous)}")
    print(f"  两表均未匹配（未处理） : {len(unmatched)}")

    if ambiguous:
        print("\n⚠️  以下邀请码在 plex_user 和 emby_user 中均能找到匹配，请人工确认：")
        for code, used_by in ambiguous:
            print(f"    code={code}  used_by={used_by}")

    if unmatched:
        print("\n⚠️  以下邀请码在 plex_user 和 emby_user 中均无匹配，请人工确认：")
        for code, used_by in unmatched:
            print(f"    code={code}  used_by={used_by}")


if __name__ == "__main__":
    backfill_invitation_service()
