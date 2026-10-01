"""fix-live-defects D3：Plex 账号同步的容错。

修复前：库里没有对应记录的 Plex 好友会让整次同步中止（TypeError 被
最外层捕获后 print），中止点之后的用户不改名，plex_id 回填、邀请记录
回填、头像刷新整段不执行；按邮箱解析 plex_id 区分大小写。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import get_session
from app.domains.accounts import service as accounts_service
from app.domains.identity.models import PlexUser


class FakeFriend:
    def __init__(self, email: str):
        self.email = email


class FakePlex:
    """按 users_by_id / 待回填邮箱构造可控的 Plex 集成替身。"""

    def __init__(self, users_by_id=None, email_to_id=None):
        self.users_by_id = users_by_id or {}
        self._email_to_id = email_to_id or {}
        self.avatars_refreshed = False

    def get_user_id_by_email(self, email: str):
        return self._email_to_id.get(email, 0)

    def get_username_by_user_id(self, user_id):
        for uid, (username, _friend) in self.users_by_id.items():
            if uid == user_id:
                return username
        return ""

    def update_all_user_avatars(self):
        self.avatars_refreshed = True


def _plex_row(where) -> PlexUser | None:
    with get_session() as session:
        row = session.execute(select(PlexUser).where(where)).scalar_one_or_none()
        if row is not None:
            session.refresh(row)
            session.expunge(row)
        return row


def _by_id(plex_id: int):
    return _plex_row(PlexUser.plex_id == int(plex_id))


def _by_email(email: str):
    return _plex_row(PlexUser.plex_email == email)


def _seed(plex_id: int | None, email: str, username: str) -> None:
    with get_session() as session:
        session.add(PlexUser(plex_id=plex_id, plex_email=email, plex_username=username))


@pytest.fixture
def no_side_effects(monkeypatch):
    from app.integrations import media_tokens

    monkeypatch.setattr(
        media_tokens, "clear_plex_tokens_for_usernames", lambda names: []
    )


def test_missing_record_does_not_abort_sync(session_env, monkeypatch, no_side_effects):
    # 四个好友：有记录且改名、无记录、有记录且改名、待回填（plex_id 为空）
    _seed(1, "one@example.com", "old_one")
    _seed(2, "two@example.com", "old_two")
    _seed(None, "four@example.com", "four")

    fake = FakePlex(
        users_by_id={
            1: ("new_one", FakeFriend("one@example.com")),
            99: ("stranger", FakeFriend("stranger@example.com")),
            2: ("new_two", FakeFriend("two@example.com")),
            4: ("four", FakeFriend("four@example.com")),
        },
        email_to_id={"four@example.com": 4},
    )
    monkeypatch.setattr(accounts_service, "Plex", lambda: fake)

    accounts_service.update_plex_info(plex_name=True, plex_id=True, plex_avatar=True)

    assert _by_id(1).plex_username == "new_one"
    assert _by_id(2).plex_username == "new_two"
    # 无记录的好友不建记录
    assert _by_id(99) is None
    # 回填阶段照常执行
    assert _by_email("four@example.com").plex_id == 4
    # 头像刷新照常执行
    assert fake.avatars_refreshed is True


def test_email_resolution_is_case_insensitive(session_env, monkeypatch):
    from app.integrations.plex import Plex

    friend = FakeFriend("user@example.com")
    friend.id = 7
    friend.username = "user"
    monkeypatch.setattr(Plex, "get_users", lambda self: [friend])

    # 与 Plex 返回的邮箱大小写不同的查询也应命中
    plex = object.__new__(Plex)
    assert plex.get_user_id_by_email("User@Example.com") == 7


def test_unique_conflict_skips_only_that_user(
    session_env, monkeypatch, no_side_effects
):
    _seed(1, "one@example.com", "old_one")
    _seed(2, "two@example.com", "old_two")
    _seed(3, "three@example.com", "old_three")
    fake = FakePlex(
        users_by_id={
            1: ("new_one", FakeFriend("two@example.com")),
            2: ("new_two", FakeFriend("two@example.com")),
            3: ("new_three", FakeFriend("three@example.com")),
        }
    )
    monkeypatch.setattr(accounts_service, "Plex", lambda: fake)

    accounts_service.update_plex_info(plex_name=True, plex_id=False, plex_avatar=False)

    assert _by_id(1).plex_username == "old_one"
    assert _by_id(2).plex_username == "new_two"
    assert _by_id(3).plex_username == "new_three"


def test_emby_refresh_continues_after_one_failure(session_env, monkeypatch):
    from app.domains.accounts import jobs as accounts_jobs
    from app.domains.identity.models import EmbyUser

    with get_session() as session:
        session.add_all(
            [
                EmbyUser(emby_id="u1", emby_username="first"),
                EmbyUser(emby_id="u2", emby_username="second"),
            ]
        )

    visited: list[str] = []

    class FakeEmby:
        def get_user_info_from_username(self, username):
            visited.append(username)
            if username == "first":
                raise RuntimeError("injected failure")

    monkeypatch.setattr(accounts_jobs, "Emby", lambda: FakeEmby())
    accounts_jobs.refresh_emby_user_info(emby_username=None)
    assert visited == ["first", "second"]


def test_renamed_user_is_updated(session_env, monkeypatch, no_side_effects):
    """有记录且改名的好友照旧被更新（修复前后行为一致）。"""
    _seed(1, "one@example.com", "old_one")
    fake = FakePlex(users_by_id={1: ("new_one", FakeFriend("one@example.com"))})
    monkeypatch.setattr(accounts_service, "Plex", lambda: fake)

    accounts_service.update_plex_info(plex_name=True, plex_id=False, plex_avatar=False)

    assert _by_id(1).plex_username == "new_one"
