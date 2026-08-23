from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from flagwatch import cli
from flagwatch.sync import SyncReport


class FakeSyncService:
    def run(self) -> SyncReport:
        return SyncReport(imported=2, analyzed=2, queued=1)


class FailedSyncService:
    def run(self) -> SyncReport:
        return SyncReport(failures=["official-feed: timeout"])


def test_sync_command_reports_counts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "build_sync_service", lambda _settings: FakeSyncService())
    runner = CliRunner()

    result = runner.invoke(cli.app, ["sync", "--database", str(tmp_path / "test.db")])

    assert result.exit_code == 0
    assert "Imported 2 events" in result.stdout
    assert "Analyzed 2 rule sets" in result.stdout
    assert "Queued 1 alert preview" in result.stdout


def test_deliver_stays_off_without_send_switch(tmp_path: Path):
    runner = CliRunner()

    result = runner.invoke(cli.app, ["deliver", "--database", str(tmp_path / "test.db")])

    assert result.exit_code == 0
    assert "Sending is disabled" in result.stdout


def test_serve_rejects_non_loopback_binding(tmp_path: Path):
    runner = CliRunner()

    result = runner.invoke(
        cli.app,
        ["serve", "--host", "0.0.0.0", "--database", str(tmp_path / "test.db")],
    )

    assert result.exit_code == 2
    assert "loopback" in result.output.lower()


def test_refresh_atomically_publishes_public_snapshot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        cli,
        "build_sync_service",
        lambda _settings, queue_notifications=False: FakeSyncService(),
    )
    runner = CliRunner()
    output = tmp_path / "public" / "events.json"

    result = runner.invoke(
        cli.app,
        [
            "refresh",
            "--database",
            str(tmp_path / "state" / "flagwatch.db"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["events"] == []
    assert list(output.parent.glob("*.tmp")) == []


def test_refresh_keeps_last_good_snapshot_when_every_source_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        cli,
        "build_sync_service",
        lambda _settings, queue_notifications=False: FailedSyncService(),
    )
    runner = CliRunner()
    output = tmp_path / "public" / "events.json"
    output.parent.mkdir()
    output.write_text('{"known":"good"}\n', encoding="utf-8")

    result = runner.invoke(
        cli.app,
        ["refresh", "--database", str(tmp_path / "state.db"), "--output", str(output)],
    )

    assert result.exit_code == 2
    assert output.read_text(encoding="utf-8") == '{"known":"good"}\n'
    assert "previous public snapshot was kept" in result.output
