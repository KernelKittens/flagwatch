from flagwatch.config import Settings


def test_delivery_is_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.send_enabled is False
    assert settings.database_path == tmp_path / "data" / "flagwatch.db"
    assert settings.ctftime_lookahead_days == 90
