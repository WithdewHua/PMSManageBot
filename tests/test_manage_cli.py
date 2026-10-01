"""Manual CLI commands preserve the two legacy operational entry points."""

from unittest.mock import Mock

from app import manage


def test_legacy_credit_sync_preserves_operation_order(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        manage, "update_plex_credits", lambda: calls.append("plex_credits")
    )
    monkeypatch.setattr(manage, "update_plex_info", lambda: calls.append("plex_info"))
    monkeypatch.setattr(
        manage, "update_emby_credits", lambda: calls.append("emby_credits")
    )
    assert manage.main(["legacy-credit-sync"]) == 0
    assert calls == ["plex_credits", "plex_info", "emby_credits"]


def test_report_preserves_defaults_and_does_not_print(monkeypatch, capsys):
    report = Mock(return_value="report body")
    monkeypatch.setattr(manage.report_service, "stats_report", report)
    assert manage.main(["report"]) == 0
    assert report.call_args.kwargs == {
        "days": 7,
        "top": 5,
        "stat": "duration",
        "refresh": False,
        "all_stats": False,
        "library_stats": False,
        "user_stats": False,
        "watched_stats": False,
        "emby": False,
    }
    assert capsys.readouterr().out == ""


def test_report_accepts_all_legacy_flags(monkeypatch):
    report = Mock()
    monkeypatch.setattr(manage.report_service, "stats_report", report)
    assert (
        manage.main(
            [
                "report",
                "--days",
                "14",
                "--top",
                "10",
                "--stat",
                "duration",
                "--refresh",
                "--all_stats",
                "--library_stats",
                "--user_stats",
                "--watched_stats",
                "--emby",
            ]
        )
        == 0
    )
    assert report.call_args.kwargs["days"] == 14
    assert report.call_args.kwargs["emby"] is True
    assert all(
        report.call_args.kwargs[name]
        for name in (
            "refresh",
            "all_stats",
            "library_stats",
            "user_stats",
            "watched_stats",
        )
    )
