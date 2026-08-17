from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_bicep_is_isolated_and_uses_low_cost_public_resources() -> None:
    bicep = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
    assert "centralus" in bicep
    assert "Standard_LRS" in bicep
    assert "Microsoft.Web/staticSites" in bicep
    assert "name: 'Free'" in bicep
    assert "allowBlobPublicAccess: false" in bicep
    assert "rg-1337-pwnsp4c3-ctf-2026" not in bicep


def test_deploy_script_enforces_function_and_safety_contract() -> None:
    script = (ROOT / "scripts" / "deploy-azure.ps1").read_text(encoding="utf-8")
    for required in (
        "rg-flagwatch-web-prod",
        "--flexconsumption-location",
        "--runtime-version 3.13",
        "--instance-memory 512",
        "--maximum-instance-count 1",
        "Storage Blob Data Contributor",
        "FLAGWATCH_SEND_ENABLED=false",
        "FLAGWATCH_AI_ENABLED=false",
        "amount = 10",
    ):
        assert required in script
    assert "rg-1337-pwnsp4c3-ctf-2026" not in script
    assert "discord" not in script.casefold()
    assert "smtp" not in script.casefold()
    assert "$env:SWA_CLI_DEPLOYMENT_TOKEN = $token" in script
    assert "--deployment-token $token" not in script
    assert "Write-Output $token" not in script
    assert "$brandedOrigin = 'https://calendar.kitsunetechnologies.org'" in script
    assert '$requiredCorsOrigins = @("https://$swaHostname", $brandedOrigin)' in script


def test_static_web_app_routes_are_unique_after_azure_normalization() -> None:
    config = json.loads((ROOT / "site" / "staticwebapp.config.json").read_text(encoding="utf-8"))
    routes = [route["route"].rstrip("/") or "/" for route in config.get("routes", [])]

    assert len(routes) == len(set(routes))


def test_caddy_route_deploy_preserves_live_config_identity_before_replace() -> None:
    script = (ROOT / "scripts" / "deploy-caddy-calendar-route.py").read_text(encoding="utf-8")

    stat_index = script.index("config_metadata = CONFIG.stat()")
    chmod_index = script.index("os.chmod(candidate, stat.S_IMODE(config_metadata.st_mode))")
    chown_index = script.index(
        "os.chown(candidate, config_metadata.st_uid, config_metadata.st_gid)"
    )
    replace_index = script.index("os.replace(candidate, CONFIG)")

    assert stat_index < chmod_index < replace_index
    assert stat_index < chown_index < replace_index
