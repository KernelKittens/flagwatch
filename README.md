# Flagwatch

Flagwatch is a private CTF research board. It imports upcoming events from CTFtime, reads reachable official rules, converts times to Central time, and keeps cited AI-policy evidence beside the useful event facts.

Every imported event remains visible. Alert previews are created only when the rules confirm that AI-assisted solving is allowed. A ban on autonomous solvers is fine. A ban on AI-assisted challenge solving suppresses the alert. Missing or conflicting rules do too.

## Run it locally

Flagwatch requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run playwright install chromium
uv run flagwatch sync
uv run flagwatch serve
```

Open `http://127.0.0.1:4814`. The dashboard can also run a sync from its **Sync now** button. A full sync may take a few minutes because official event sites are fetched one at a time with network safety checks.

The SQLite database defaults to `data/flagwatch.db`. Override it with `--database` on any command or with `FLAGWATCH_DATABASE_PATH`.

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
