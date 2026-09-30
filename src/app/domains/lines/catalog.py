"""Line catalog storage adapter.

The storage remains the legacy settings/Core KV combination until the
``move-line-catalog-to-database`` change.  Keeping these operations here gives
other domains one stable interface without changing persistence semantics.
"""

from __future__ import annotations

from app.core import kv as core_kv
from app.core.config import settings
from app.core.log import logger


def normal_lines() -> list[str]:
    return list(settings.STREAM_BACKEND)


def premium_lines() -> list[str]:
    return list(settings.PREMIUM_STREAM_BACKEND)


def free_premium_lines() -> list[str]:
    configs = core_kv.get_all("free_premium_line")
    return [key for key, value in configs.items() if value == "1"]


def line_tags(name: str) -> list[str]:
    tags_str = core_kv.get("line_tag", name)
    if not tags_str:
        return []
    return [tag.strip() for tag in tags_str.split(",") if tag.strip()]


def all_line_tags() -> dict[str, list[str]]:
    configs = core_kv.get_all("line_tag")
    return {
        name: [tag.strip() for tag in value.split(",") if tag.strip()]
        for name, value in configs.items()
    }


def add_line(name: str, *, premium: bool) -> None:
    setting_name = "PREMIUM_STREAM_BACKEND" if premium else "STREAM_BACKEND"
    lines = premium_lines() if premium else normal_lines()
    if name in lines:
        raise ValueError("该线路已存在")
    other_lines = normal_lines() if premium else premium_lines()
    if name in other_lines:
        raise ValueError("该线路已存在于另一线路列表中")
    new_lines = lines + [name]
    setattr(settings, setting_name, new_lines)
    settings.save_config_to_env_file({setting_name: ",".join(new_lines)})


def delete_line(name: str, *, premium: bool) -> None:
    setting_name = "PREMIUM_STREAM_BACKEND" if premium else "STREAM_BACKEND"
    lines = premium_lines() if premium else normal_lines()
    if name not in lines:
        raise ValueError("该线路不存在")
    new_lines = [line for line in lines if line != name]
    setattr(settings, setting_name, new_lines)
    settings.save_config_to_env_file({setting_name: ",".join(new_lines)})


def set_line_tags(name: str, tags: list[str]) -> bool:
    if not tags:
        return core_kv.delete("line_tag", name)
    tags_str = ",".join(set(tags))
    core_kv.upsert("line_tag", name, tags_str)
    return True


def delete_line_tags(name: str) -> bool:
    return core_kv.delete("line_tag", name)


def set_free_premium_lines(names: list[str]) -> bool:
    try:
        existing = set(free_premium_lines())
        desired = set(names)
        for line in existing - desired:
            core_kv.delete("free_premium_line", line)
        for line in desired - existing:
            core_kv.upsert("free_premium_line", line, "1")
        logger.info("设置免费高级线路成功，共 %s 条线路", len(names))
        return True
    except Exception as error:
        logger.error("设置免费高级线路失败: %s", error)
        return False


__all__ = [
    "add_line",
    "all_line_tags",
    "delete_line",
    "delete_line_tags",
    "free_premium_lines",
    "line_tags",
    "normal_lines",
    "premium_lines",
    "set_free_premium_lines",
    "set_line_tags",
]
