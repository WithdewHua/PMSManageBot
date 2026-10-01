"""CLI contract tests for the manual Telegram ID rebind command."""

from __future__ import annotations

import pytest

from app import manage
from app.domains.tg_rebind.types import RebindReport


def test_parser_requires_one_locator_and_to_id() -> None:
    parser = manage._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["rebind-tg-id", "--to", "2"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["rebind-tg-id", "--from", "1", "--to", "2", "--plex-email", "a@b"]
        )


def test_rebind_cli_success_and_dry_run_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(manage, "register_all", lambda: None)
    monkeypatch.setattr(
        manage.tg_rebind_service,
        "rebind",
        lambda *args, **kwargs: RebindReport(
            1, 2, kwargs["dry_run"], {"credits": {"statistics.credits": 1}}
        ),
    )

    assert manage.main(["rebind-tg-id", "--to", "2", "--from", "1", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "dry-run" in output
    assert "credits.statistics.credits: 1" in output


def test_rebind_cli_maps_rejection_and_not_found(monkeypatch, capsys) -> None:
    monkeypatch.setattr(manage, "register_all", lambda: None)
    from app.domains.identity.types import TgIdReassignIssue
    from app.domains.tg_rebind.exceptions import (
        TgRebindAccountNotFound,
        TgRebindRejected,
    )

    monkeypatch.setattr(
        manage.tg_rebind_service,
        "rebind",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            TgRebindRejected(
                [TgIdReassignIssue("conflict", "badges", "duplicate", ("7",))]
            )
        ),
    )
    assert manage.main(["rebind-tg-id", "--to", "2", "--from", "1"]) == 2
    assert "duplicate" in capsys.readouterr().out

    monkeypatch.setattr(
        manage.tg_rebind_service,
        "rebind",
        lambda *args, **kwargs: (_ for _ in ()).throw(TgRebindAccountNotFound("1")),
    )
    assert manage.main(["rebind-tg-id", "--to", "2", "--from", "1"]) == 3
    assert "account not found" in capsys.readouterr().out
