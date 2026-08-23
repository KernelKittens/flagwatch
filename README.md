# Flagwatch

Flagwatch imports the previous 31 days and next 90 days of events from CTFtime, reads reachable official rules, and keeps cited event intelligence beside the useful event facts. Its public surface is a read-only month calendar. The local operator dashboard remains private.

The public calendar omits events whose confirmed rules ban all AI-assisted challenge work. A ban on autonomous solvers alone is fine. Missing or conflicting rules remain visible as unverified and never trigger an alert. The private operator data keeps every imported event and its evidence for review.

The scan strip reports the current source coverage instead of treating every HTTP 200 response as a successful rule scan. `Read` means Flagwatch found usable official text. `Limited` means a site responded but useful content was incomplete, blocked behind JavaScript, or one of its rule pages failed. `Failed` means the official site could not be reached. Limited, failed, conflicting, and stale scans never alert.

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

The public deployment uses its own `rg-flagwatch-web-prod` resource group in Central US. Azure Static Web Apps serves the calendar. A Python 3.13 Flex Consumption Function refreshes a private Blob-backed database every six hours and exposes only sanitized event JSON. One 512 MiB HTTP instance stays always ready so ordinary calendar loads do not depend on a cold start.

Run `scripts/deploy-azure.ps1` from an authenticated Azure CLI session with `FLAGWATCH_AI_API_KEY` set in that process. The script validates tests and Bicep before creating resources, seeds the last-good snapshot, verifies always-ready capacity, sets a $10 monthly budget alert, and returns the site and API URLs. It never changes the existing CTF Discord bot resource group.

The model credential is stored only in Azure Function configuration and is never committed. The Azure refresh keeps alert generation and delivery disabled.

## AI-policy analysis

The built-in rule parser handles explicit AI permissions and bans without depending on a model. It reads crawler-visible page content, useful page metadata, same-origin rule links, and bounded same-origin sitemap entries. DeepSeek V4 Pro extracts additional public event and rules intelligence. A content fingerprint reuses prior results when the sources have not changed.

Set these environment variables to enable the fallback:

```text
FLAGWATCH_AI_ENABLED=true
FLAGWATCH_AI_ENDPOINT=<OpenAI-compatible chat completions URL>
FLAGWATCH_AI_MODEL=<model name>
FLAGWATCH_AI_API_KEY=<secret>
```

A model result is accepted only when each evidence quote appears on its declared fetched source page. Unsupported claims are discarded. A model classification cannot override conflicting evidence or bypass the stale-source alert gate.

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
