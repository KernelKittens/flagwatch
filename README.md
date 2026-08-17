# Flagwatch

Flagwatch imports upcoming events from CTFtime, reads reachable official rules, and keeps cited AI-policy evidence beside the useful event facts. Its public surface is a read-only month calendar. The local operator dashboard remains private.

The public calendar omits events whose confirmed rules ban all AI-assisted challenge work. A ban on autonomous solvers alone is fine. Missing or conflicting rules remain visible as unverified and never trigger an alert. The private operator data keeps every imported event and its evidence for review.

## Run it locally

Flagwatch requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run playwright install chromium
uv run flagwatch sync
uv run flagwatch serve
```

## License

MIT. See [LICENSE](LICENSE).

Open `http://127.0.0.1:4814`. The dashboard can also run a sync from its **Sync now** button. A full sync may take a few minutes because official event sites are fetched one at a time with network safety checks.

The SQLite database defaults to `data/flagwatch.db`. Override it with `--database` on any command or with `FLAGWATCH_DATABASE_PATH`.

The public calendar lives in `site/`. Its browser timezone prompt defaults to America/Chicago when detection is unavailable. During local static-site development, serve the folder and provide `GET /api/events` using the public snapshot contract.

## Azure deployment

The public deployment uses its own `rg-flagwatch-web-prod` resource group in Central US. Azure Static Web Apps serves the calendar. A Python 3.13 Flex Consumption Function refreshes a private Blob-backed database every six hours and exposes only sanitized event JSON.

Run `scripts/deploy-azure.ps1` from an authenticated Azure CLI session. The script validates tests and Bicep before creating resources, seeds the last-good snapshot, sets a $10 monthly budget alert, and returns the site and API URLs. It never changes the existing CTF Discord bot resource group.

Notifications and model-provider credentials are not deployed. The Azure refresh keeps alert generation and delivery disabled.

## AI-policy analysis

The built-in rule parser handles explicit AI permissions and bans without sending rule text to a model. Optional model fallback runs only when the parser returns `unknown` and the source pages do not conflict.

Set these environment variables to enable the fallback:

```text
FLAGWATCH_AI_ENABLED=true
FLAGWATCH_AI_ENDPOINT=<OpenAI-compatible chat completions URL>
FLAGWATCH_AI_MODEL=<model name>
FLAGWATCH_AI_API_KEY=<secret>
```

A model result is accepted only when its evidence quote appears on a fetched source page. Otherwise the policy stays `unknown` and cannot alert.

## Alerts

Syncing creates local alert previews. It does not send them. Delivery requires `FLAGWATCH_SEND_ENABLED=true` and either a Discord webhook or a complete SMTP configuration.

```powershell
uv run flagwatch deliver
```

Discord needs `FLAGWATCH_DISCORD_WEBHOOK_URL`. Email needs the six `FLAGWATCH_SMTP_*` variables shown in [.env.example](.env.example). Keep secrets in `.env.local`, which Git ignores.

## Checks

```powershell
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Browser tests start a temporary loopback server, run axe, verify keyboard access and 320 px layout, then save screenshots under `artifacts/`.
