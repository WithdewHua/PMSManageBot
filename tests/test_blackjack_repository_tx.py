from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.domains.blackjack import config, repository

TX_EXPORTS = (
    "create_blackjack_hand_tx",
    "blackjack_hit_tx",
    "blackjack_stand_tx",
    "blackjack_double_tx",
    "blackjack_surrender_tx",
    "settle_blackjack_hand_by_timeout_tx",
    "create_blackjack_tournament_hand_tx",
    "blackjack_tournament_hit_tx",
    "blackjack_tournament_stand_tx",
    "blackjack_tournament_double_tx",
    "blackjack_tournament_surrender_tx",
    "settle_blackjack_tournament_tx",
    "register_blackjack_tournament_tx",
    "get_blackjack_config_tx",
    "get_blackjack_config_dict_tx",
    "set_blackjack_config_tx",
    "apply_blackjack_retention_tx",
    "get_user_blackjack_stats_tx",
    "get_blackjack_admin_stats_tx",
    "credit_tournament_wallet_tx",
)

#: 只读聚合模块（analytics）提供的 `*_tx` 包装：它们不是 mixin 方法，所以不参与
#: 上面那条“mixin 里的 `_tx` 方法必须逐个登记”的集合相等断言，但同样必须
#: 以 `session` 为首参。
ANALYTICS_TX_EXPORTS = (
    "cash_hand_metrics_tx",
    "count_tournament_entries_tx",
)


def test_repository_reexports_config_constants_for_compatibility() -> None:
    for name in config.__all__:
        assert getattr(repository, name) is getattr(config, name)


def test_module_tx_exports_have_explicit_caller_session() -> None:
    for name in (*TX_EXPORTS, *ANALYTICS_TX_EXPORTS):
        signature = inspect.signature(getattr(repository, name))
        assert next(iter(signature.parameters)) == "session"
        assert getattr(repository, name).__module__ == repository.__name__


def _planned_mixin_modules() -> list[Path]:
    """The modules the reviewed split plan declares for this repository."""
    import tomllib

    root = Path(__file__).parents[1]
    with (root / "scripts/refactor/split_plans.toml").open("rb") as stream:
        plan = tomllib.load(stream)["blackjack_repository"]
    package = root / "src" / Path(*plan["package"].split("."))
    return [package / f"{stem}.py" for stem in plan["mixins"]]


def test_extracted_tx_methods_do_not_open_or_commit_sessions() -> None:
    tx_names: set[str] = set()
    modules = _planned_mixin_modules()
    assert len(modules) > 1
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tx_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.endswith("_tx")
        ]
        tx_names.update(node.name for node in tx_functions)
        for node in tx_functions:
            call_names = []
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                function = child.func
                call_names.append(
                    function.attr
                    if isinstance(function, ast.Attribute)
                    else function.id
                    if isinstance(function, ast.Name)
                    else ""
                )
            assert "get_session" not in call_names, node.name
            assert "commit" not in call_names, node.name
            assert "close" not in call_names, node.name

    assert tx_names == set(TX_EXPORTS)


def test_no_numbered_repository_modules_remain() -> None:
    """子主题拆包后不允许再出现 part_<数字> 模块（design D1）。"""
    package = Path(__file__).parents[1] / "src/app/domains/blackjack/repository"
    numbered = [
        path.name
        for path in package.glob("part_*.py")
        if path.stem.split("_")[-1].isdigit()
    ]
    assert numbered == []


def test_module_tx_exports_forward_the_same_session(monkeypatch) -> None:
    sentinel = object()
    calls: list[tuple[str, tuple, dict]] = []

    class FakeRepository:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                calls.append((name, args, kwargs))
                return {"method": name}

            return method

    monkeypatch.setattr(repository, "_repository", FakeRepository())
    result = repository.blackjack_hit_tx(
        sentinel, 1001, 55, jackpot_config={"jackpot_enabled": True}
    )

    assert result == {"method": "blackjack_hit_tx"}
    assert calls == [
        (
            "blackjack_hit_tx",
            (sentinel, 1001, 55),
            {"jackpot_config": {"jackpot_enabled": True}},
        )
    ]


def test_registration_tx_wrapper_forwards_session_and_inputs(monkeypatch) -> None:
    sentinel = object()
    calls: list[tuple[str, tuple, dict]] = []

    class FakeRepository:
        def register_blackjack_tournament_tx(self, *args, **kwargs):
            calls.append(("register_blackjack_tournament_tx", args, kwargs))
            return {"ok": True}

    monkeypatch.setattr(repository, "_repository", FakeRepository())
    result = repository.register_blackjack_tournament_tx(
        sentinel,
        1001,
        77,
        config={"enabled": True},
        now_ms=123,
    )

    assert result == {"ok": True}
    assert calls == [
        (
            "register_blackjack_tournament_tx",
            (sentinel, 1001, 77),
            {"config": {"enabled": True}, "now_ms": 123},
        )
    ]


def test_config_tx_wrapper_forwards_session(monkeypatch) -> None:
    sentinel = object()
    calls: list[tuple[str, tuple, dict]] = []

    class FakeRepository:
        def get_blackjack_config_dict_tx(self, *args, **kwargs):
            calls.append(("get_blackjack_config_dict_tx", args, kwargs))
            return {"enabled": True}

    monkeypatch.setattr(repository, "_repository", FakeRepository())
    result = repository.get_blackjack_config_dict_tx(sentinel)

    assert result == {"enabled": True}
    assert calls == [("get_blackjack_config_dict_tx", (sentinel,), {})]


def test_statistics_tx_wrapper_forwards_session(monkeypatch) -> None:
    sentinel = object()
    calls: list[tuple[str, tuple, dict]] = []

    class FakeRepository:
        def get_user_blackjack_stats_tx(self, *args, **kwargs):
            calls.append(("get_user_blackjack_stats_tx", args, kwargs))
            return {"total_hands": 0}

    monkeypatch.setattr(repository, "_repository", FakeRepository())
    result = repository.get_user_blackjack_stats_tx(sentinel, 1001)

    assert result == {"total_hands": 0}
    assert calls == [("get_user_blackjack_stats_tx", (sentinel, 1001), {})]
