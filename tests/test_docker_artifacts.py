from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_images_run_as_non_root_and_have_health_checks() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert "USER 1000:1000" in dockerfile
    assert dockerfile.count("HEALTHCHECK") == 2
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "UV_PROJECT_ENVIRONMENT=/opt/flagwatch/.venv" in dockerfile
    assert "/opt/flagwatch/.venv /opt/flagwatch/.venv" in dockerfile
    assert "chmod 0555 /usr/local/bin/flagwatch-sync-loop" in dockerfile
    assert "cp /usr/bin/caddy /usr/local/bin/caddy-unprivileged" in dockerfile
    assert 'ENTRYPOINT ["caddy-unprivileged"' in dockerfile


def test_compose_has_split_services_last_good_volumes_and_optional_litellm() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "  web:\n" in compose
    assert "  sync:\n" in compose
    assert "  litellm:\n" in compose
    assert compose.count("    read_only: true") >= 2
    assert compose.count("    restart: unless-stopped") == 3
    assert "/config:size=8m,mode=0700,uid=1000,gid=1000" in compose
    assert '    profiles: ["litellm"]' in compose
    assert "    image: ghcr.io/berriai/litellm:v1.94.0" in compose
    assert "      - flagwatch_public:/srv/data:ro" in compose
    assert "      - flagwatch_public:/data/public" in compose
    assert "  flagwatch_public:\n" in compose
    assert "  flagwatch_state:\n" in compose


def test_caddy_serves_api_from_read_only_last_good_snapshot() -> None:
    config = (ROOT / "docker" / "Caddyfile").read_text(encoding="utf-8")

    assert "handle /healthz" in config
    assert "handle /api/events" in config
    assert "root * /srv/data" in config
    assert "rewrite * /events.json" in config
    assert "stale-if-error=86400" in config


def test_sync_loop_never_removes_previous_snapshot_on_failure() -> None:
    script = (ROOT / "docker" / "sync-loop.sh").read_text(encoding="utf-8")

    assert "flagwatch refresh" in script
    assert "last-good public snapshot is still active" in script
    assert "rm " not in script
