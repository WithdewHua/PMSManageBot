"""Unit tests for scripts/migrate_line_traffic_stats.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.migrate_line_traffic_stats import migrate_historical_traffic_data


def test_migrate_traffic_no_records() -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar.return_value = None

    with patch("scripts.migrate_line_traffic_stats.get_session") as mock_get_sess:
        mock_get_sess.return_value.__enter__.return_value = mock_session
        results = migrate_historical_traffic_data(start_month=None, end_month="2026-05")

        assert results["total_months"] == 0
        assert results["success_months"] == []


def test_migrate_traffic_invalid_date_format() -> None:
    results = migrate_historical_traffic_data(
        start_month="bad-format", end_month="2026-05"
    )
    assert results["total_months"] == 0


def test_migrate_traffic_start_after_end() -> None:
    results = migrate_historical_traffic_data(
        start_month="2026-06", end_month="2026-05"
    )
    assert results["total_months"] == 0


def test_migrate_traffic_batch_success() -> None:
    mock_session = MagicMock()
    # original_count = 100
    mock_session.execute.return_value.scalar.return_value = 100

    with (
        patch("scripts.migrate_line_traffic_stats.get_session") as mock_get_sess,
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.aggregate_monthly_traffic_data",
            return_value=(True, "聚合成功"),
        ) as mock_aggregate,
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.cleanup_monthly_traffic_data",
            return_value=(True, "清理成功"),
        ) as mock_cleanup,
    ):
        mock_get_sess.return_value.__enter__.return_value = mock_session
        results = migrate_historical_traffic_data(
            start_month="2026-01",
            end_month="2026-02",
            batch_process=True,
            confirm_cleanup=True,
        )

        assert results["total_months"] == 2
        assert results["success_months"] == ["2026-01", "2026-02"]
        assert results["cleanup_months"] == ["2026-01", "2026-02"]
        assert results["failed_months"] == []
        assert mock_aggregate.call_count == 2
        assert mock_cleanup.call_count == 2


def test_migrate_traffic_skipped_when_zero_records() -> None:
    mock_session = MagicMock()
    # original_count = 0
    mock_session.execute.return_value.scalar.return_value = 0

    with (
        patch("scripts.migrate_line_traffic_stats.get_session") as mock_get_sess,
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.aggregate_monthly_traffic_data"
        ) as mock_aggregate,
    ):
        mock_get_sess.return_value.__enter__.return_value = mock_session
        results = migrate_historical_traffic_data(
            start_month="2026-01",
            end_month="2026-01",
            batch_process=True,
            confirm_cleanup=True,
        )

        assert results["total_months"] == 1
        assert results["skipped_months"] == ["2026-01"]
        assert results["success_months"] == []
        mock_aggregate.assert_not_called()


def test_migrate_traffic_aggregation_failure() -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar.return_value = 50

    with (
        patch("scripts.migrate_line_traffic_stats.get_session") as mock_get_sess,
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.aggregate_monthly_traffic_data",
            return_value=(False, "聚合数据库错误"),
        ),
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.cleanup_monthly_traffic_data"
        ) as mock_cleanup,
    ):
        mock_get_sess.return_value.__enter__.return_value = mock_session
        results = migrate_historical_traffic_data(
            start_month="2026-01",
            end_month="2026-01",
            batch_process=True,
            confirm_cleanup=True,
        )

        assert results["failed_months"] == ["2026-01"]
        assert results["success_months"] == []
        mock_cleanup.assert_not_called()


def test_migrate_traffic_cleanup_failure() -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar.return_value = 50

    with (
        patch("scripts.migrate_line_traffic_stats.get_session") as mock_get_sess,
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.aggregate_monthly_traffic_data",
            return_value=(True, "聚合成功"),
        ),
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.cleanup_monthly_traffic_data",
            return_value=(False, "清理失败"),
        ),
    ):
        mock_get_sess.return_value.__enter__.return_value = mock_session
        results = migrate_historical_traffic_data(
            start_month="2026-01",
            end_month="2026-01",
            batch_process=True,
            confirm_cleanup=True,
        )

        assert results["success_months"] == ["2026-01"]
        assert results["cleanup_failed_months"] == ["2026-01"]


def test_migrate_traffic_interactive_cancel_start() -> None:
    with patch("builtins.input", return_value="no"):
        results = migrate_historical_traffic_data(
            start_month="2026-01",
            end_month="2026-01",
            batch_process=False,
            confirm_cleanup=False,
        )

        assert results["total_months"] == 1
        assert results["success_months"] == []


def test_migrate_traffic_interactive_skip_cleanup() -> None:
    mock_session = MagicMock()
    mock_session.execute.return_value.scalar.return_value = 50

    # User inputs:
    # 1. "yes" for start confirm
    # 2. "no" for cleanup confirm
    with (
        patch("builtins.input", side_effect=["yes", "no"]),
        patch("scripts.migrate_line_traffic_stats.get_session") as mock_get_sess,
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.aggregate_monthly_traffic_data",
            return_value=(True, "聚合成功"),
        ),
        patch(
            "scripts.migrate_line_traffic_stats.traffic_service.cleanup_monthly_traffic_data"
        ) as mock_cleanup,
    ):
        mock_get_sess.return_value.__enter__.return_value = mock_session
        results = migrate_historical_traffic_data(
            start_month="2026-01",
            end_month="2026-01",
            batch_process=False,
            confirm_cleanup=False,
        )

        assert results["success_months"] == ["2026-01"]
        assert results["cleanup_months"] == []
        mock_cleanup.assert_not_called()
