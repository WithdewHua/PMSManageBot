"""Seed a reviewable relocation map; uncertain items remain explicitly TODO.

An existing map is only extended with --merge, retaining reviewed entries by ID;
--force explicitly discards existing review edits. The draft is not authorization
to relocate code: tasks 3.2–5.1 review every
source group and replace TODOs before moving it.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import tomllib
from bisect import bisect_right
from pathlib import Path

from scripts.refactor.inventory import ROOT, SOURCE, Item, inventory

DESTINATIONS = {
    "app.config": "app.core.config",
    "app.log": "app.core.log",
    "app.scheduler": "app.core.scheduler",
    "app.databases.session": "app.core.db",
    "app.databases.redis": "app.core.redis",
    "app.databases.cache": "app.core.cache",
    "app.blackjack_engine": "app.domains.blackjack.rules",
    "app.premium": "app.domains.premium.service",
    "app.utils.number": "app.core.number",
    "app.utils.system": "app.core.system",
    "app.utils.tautulli_history": "app.integrations.tautulli_history",
    "app.webapp.auth": "app.core.auth",
    "app.webapp.middlewares": "app.api.middlewares",
    "app.webapp.startup.lifespan": "app.api.lifespan",
    "app.webapp": "app.api.app",
    "app.handlers.start": "app.bot.start",
    "app.handlers.rank": "app.domains.rankings.bot",
    "app.handlers.status": "app.domains.reports.bot",
    "app.models.models:Base": "app.core.db",
    "app.models.models:SystemConfig": "app.core.kv",
}
CLIENTS = {"plex", "emby", "tautulli", "overseerr", "upay", "vaultwarden"}
ROUTE_DOMAINS = {
    "auction": "auction",
    "blackjack": "blackjack",
    "blackjack_tournament": "blackjack",
    "luckywheel": "luckywheel",
    "prediction": "prediction",
    "treasure": "treasure",
    "badge": "badges",
    "crypto_donation": "crypto_donation",
    "donation": "donation",
    "gift_pack": "gift_pack",
    "invitation": "invitation",
    "premium": "premium",
    "rankings": "rankings",
    "system": "reports",
    "vaultwarden": "vaultwarden",
}
SCHEMA_DOMAINS = {**ROUTE_DOMAINS, "ranking": "rankings", "user": "profile"}
# Section labels are read from the actual file rather than inferred from the
# method name. Neutral sections are left for human review in B1.
SECTION_DOMAINS = {
    "Treasure (夺宝) Operations": "treasure",
    "Prediction Market (预测游戏) Operations": "prediction",
    "Blackjack (21 点) Operations": "blackjack",
    "21 点锦标赛": "blackjack",
    "赛内手牌：结算适配层与动作": "blackjack",
    "Rank Operations": "rankings",
    "Wheel Operations": "luckywheel",
    "Premium Operations": "premium",
    "Auction Operations": "auction",
    "Traffic Statistics Operations": "traffic",
    "Donation Management Operations": "donation",
    "Crypto Donation Orders Operations": "crypto_donation",
    "Badge Management": "badges",
    "Gift Pack Operations": "gift_pack",
    "Invitation Operations": "invitation",
    "Invitation Query Operations": "invitation",
    "Line Management Operations": "lines",
    "SystemConfig 配置管理相关方法": "core.kv",
    "免费高级线路相关方法": "lines",
    "线路标签相关方法": "lines",
    "幸运大转盘配置相关方法": "luckywheel",
    "21 点配置相关方法": "blackjack",
    "线路调度功能相关方法": "lines",
    "下载/同步权限解锁功能相关方法": "media_access",
    "Tautulli 幽灵会话清理": "watch_rewards",
}


def _sections(path: Path) -> tuple[list[int], list[str]]:
    """Extract all section starts, including unknown sections that end an inference."""
    lines = path.read_text(encoding="utf-8").splitlines()
    numbers: list[int] = []
    labels: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith("    #"):
            continue
        match = re.fullmatch(r"    # [=-]{3,}\s*(.*?)\s*[=-]{3,}\s*", line)
        if match and match.group(1).strip():
            value = match.group(1).strip()
        elif (
            re.fullmatch(r"    # [=-]{3,}\s*", line)
            and index + 2 < len(lines)
            and re.fullmatch(r"    # [=-]{3,}\s*", lines[index + 2])
            and lines[index + 1].startswith("    # ")
        ):
            value = lines[index + 1][6:].strip()
        else:
            continue
        # Never allow an unrelated section to inherit the last known owner.
        numbers.append(index + 1)
        labels.append(value)
    return numbers, labels


def _route_paths(path: Path) -> dict[str, str]:
    """Look at decorators, not a function's name, when splitting large routers."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    paths: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            if not isinstance(
                decorator.func, ast.Attribute
            ) or decorator.func.attr not in {
                "get",
                "post",
                "put",
                "delete",
                "patch",
                "api_route",
            }:
                continue
            if isinstance(decorator.args[0], ast.Constant) and isinstance(
                decorator.args[0].value, str
            ):
                paths[node.name] = decorator.args[0].value
                break
    return paths


def _route_domain(path: str) -> str | None:
    parts = {part.lower().replace("-", "_") for part in path.split("/") if part}
    if parts & {"info", "user_info"} and not parts & {"premium", "nsfw"}:
        return "profile"
    for keys, domain in (
        ({"gift_pack", "gift_packs"}, "gift_pack"),
        ({"blackjack", "tournament"}, "blackjack"),
        ({"prediction"}, "prediction"),
        ({"treasure"}, "treasure"),
        ({"auction"}, "auction"),
        ({"wheel", "luckywheel"}, "luckywheel"),
        ({"badge", "badges"}, "badges"),
        ({"premium"}, "premium"),
        ({"donation"}, "donation"),
        ({"line", "lines", "line_tags", "plex_lines", "emby_lines"}, "lines"),
        ({"bind", "account", "accounts"}, "accounts"),
        ({"invitation", "invite"}, "invitation"),
    ):
        if parts & keys:
            return domain
    return None


def destination(
    item: Item,
    *,
    section_cache: dict[str, tuple[list[int], list[str]]],
    route_cache: dict[str, dict[str, str]],
) -> tuple[str, str | None, str]:
    """Return target module, target class if applicable, and inference reason."""
    module, name = item.module, item.name
    if module == "app.databases.db" and name.startswith("DatabaseORM."):
        source = ROOT / item.path
        numbers, labels = section_cache.setdefault(item.path, _sections(source))
        position = bisect_right(numbers, item.start_line) - 1
        section = labels[position] if position >= 0 else ""
        domain = SECTION_DOMAINS.get(section)
        if name.startswith("DatabaseORM._CurWrapper"):
            return "TODO", None, "manual review: legacy cursor adapter"
        if domain == "core.kv":
            return "app.core.kv", "SystemConfigRepository", f"db.py section: {section}"
        if domain and name.count(".") == 1:
            target = f"app.domains.{domain}.repository"
            return (
                target,
                f"{''.join(word.title() for word in domain.split('_'))}Repository",
                f"db.py section: {section}",
            )
        return "TODO", None, f"db.py section: {section or 'unclassified'}"
    if module == "app.databases.db" and name in {"DatabaseORM", "db"}:
        return "app.databases.db", None, "transitional facade assembly"
    for key, target in DESTINATIONS.items():
        if (
            module == key
            or f"{module}:{name}" == key
            or f"{module}:{name.split('.')[0]}" == key
        ):
            return target, None, "design D9 module / model rule"
    if module.startswith("app.modules."):
        client = module.rsplit(".", 1)[-1]
        if client in CLIENTS:
            return f"app.integrations.{client}", None, "external client module"
        if client == "custom_line":
            return "TODO", None, "business module: review role within custom_lines"
    if module.startswith("app.webapp.schemas."):
        domain = SCHEMA_DOMAINS.get(module.rsplit(".", 1)[-1])
        if domain:
            return f"app.domains.{domain}.schemas", None, "schema module name"
    if module.startswith("app.webapp.routers."):
        basename = module.rsplit(".", 1)[-1]
        domain = ROUTE_DOMAINS.get(basename)
        if domain:
            return f"app.domains.{domain}.router", None, "router module name"
        if basename in {"user", "admin"} and item.kind == "function":
            route_paths = route_cache.setdefault(
                item.path, _route_paths(ROOT / item.path)
            )
            route = route_paths.get(name)
            domain = _route_domain(route) if route else None
            if domain:
                role = "admin_router" if basename == "admin" else "router"
                return f"app.domains.{domain}.{role}", None, f"route path: {route}"
    return "TODO", None, "ambiguous: human review required"


def seed(items: list[Item]) -> list[dict[str, str]]:
    """Generate a deterministic draft, propagating class targets to fields."""
    sections: dict[str, tuple[list[int], list[str]]] = {}
    routes: dict[str, dict[str, str]] = {}
    targets: dict[str, tuple[str, str | None, str]] = {}
    result: list[dict[str, str]] = []
    for item in items:
        target, target_class, reason = destination(
            item, section_cache=sections, route_cache=routes
        )
        parent = item.name.rpartition(".")[0]
        if target == "TODO" and parent and f"{item.module}:{parent}" in targets:
            inherited = targets[f"{item.module}:{parent}"]
            if inherited[0] != "TODO":
                target, _ignored, reason = inherited
        targets[item.id] = (target, target_class, reason)
        record = {"id": item.id, "target": target, "kind": item.kind, "reason": reason}
        if item.id == "app.databases.db:DatabaseORM":
            record["action"] = "assemble"
        if target_class and item.kind in {"method", "attribute"}:
            record["class"] = target_class
        result.append(record)
    return result


def write_mapping(records: list[dict[str, str]], path: Path) -> None:
    """Write a portable TOML mapping with stable item order."""
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(
            "# Generated draft. Review TODO entries before each relocation batch.\n"
        )
        for record in records:
            output.write("\n[[items]]\n")
            keys = ("id", "target", "action", "class", "kind", "reason")
            for key in (*keys, *sorted(set(record) - set(keys))):
                if key in record:
                    if not isinstance(record[key], (str, bool, int)):
                        raise TypeError(
                            f"unsupported mapping field {key}: {record['id']}"
                        )
                    output.write(
                        f"{key} = {json.dumps(record[key], ensure_ascii=False)}\n"
                    )


def merge_mapping(records: list[dict[str, str]], path: Path) -> list[dict[str, str]]:
    """Preserve reviewed IDs; fail rather than silently discard stale entries."""
    with path.open("rb") as existing_file:
        existing = tomllib.load(existing_file)["items"]
    by_id = {record["id"]: record for record in existing}
    if len(by_id) != len(existing):
        raise ValueError("existing map has duplicate IDs")
    new_ids = {record["id"] for record in records}
    if stale := set(by_id) - new_ids:
        raise ValueError(f"existing map contains stale IDs: {sorted(stale)[:5]}")
    merged: list[dict[str, str]] = []
    for record in records:
        previous = by_id.get(record["id"])
        if previous is None:
            merged.append(record)
            continue
        # Upgrading this known facade marker is additive; never change a
        # reviewed target, class, reason or existing action.
        if record.get("action") == "assemble" and "action" not in previous:
            previous = {**previous, "action": "assemble"}
        merged.append({**record, **previous})
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "scripts/refactor/mapping.toml"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the existing map, including reviewed entries",
    )
    parser.add_argument(
        "--merge", action="store_true", help="Only add missing IDs to an existing map"
    )
    args = parser.parse_args()
    if args.force and args.merge:
        parser.error("--force and --merge are mutually exclusive")
    if args.output.exists() and not (args.force or args.merge):
        parser.error(f"{args.output} exists; use --merge or explicit --force")
    records = seed(inventory(SOURCE.rglob("*.py")))
    if args.output.exists() and args.merge:
        try:
            records = merge_mapping(records, args.output)
        except ValueError as error:
            parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_mapping(records, args.output)
    print(
        f"Wrote {len(records)} entries: {sum(r['target'] == 'TODO' for r in records)} TODO"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
