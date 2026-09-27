from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.domains.blackjack import repository

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
)


def test_module_tx_exports_have_explicit_caller_session() -> None:
    for name in TX_EXPORTS:
        signature = inspect.signature(getattr(repository, name))
        assert next(iter(signature.parameters)) == "session"
        assert getattr(repository, name).__module__ == repository.__name__


def test_extracted_tx_methods_do_not_open_or_commit_sessions() -> None:
    for filename in ("part_3.py", "part_6.py"):
        path = (
            Path(__file__).parents[1]
            / "src/app/domains/blackjack/repository"
            / filename
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.endswith("_tx"):
                continue
            calls = [
                ast.unparse(child)
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
            ]
            assert not any("get_session" in call for call in calls), node.name
            assert not any("commit" in call for call in calls), node.name
            assert not any("close" in call for call in calls), node.name


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
