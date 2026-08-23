# Flagwatch

Flagwatch is a white-label CTF calendar and source-intelligence collector. It keeps the previous 31 days and next 90 days visible, reads official rules, attaches exact evidence quotes, and shows where every event fact came from.

Live deployment: [calendar.kernelkittens.team](https://calendar.kernelkittens.team)

## What it collects

- Optional CTFtime API listings
- ICS and JSON event feeds
- Official organizer calendars and event pages
- CTFd challenge and scoreboard summaries
- rCTF challenge and leaderboard summaries
- Official rule pages and bounded same-origin links

When sources disagree, Flagwatch keeps the preferred value, records the conflicting value, links both sources, and suppresses alerts for safety-relevant conflicts. A failed refresh never replaces the last-good public snapshot.

## Start with Docker

```sh
git clone https://github.com/KernelKittens/flagwatch.git
cd flagwatch
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:8080`. The default source file includes the official Hack The Box events page. Edit [`sources.json`](sources.json) to add feeds or event platforms. CTFtime stays off until `FLAGWATCH_CTFTIME_ENABLED=true` is set in `.env`.

The deployment runs two containers:

- `sync` refreshes source data every six hours and atomically publishes a last-good snapshot.
- `web` serves the light public calendar and read-only `/api/events` endpoint.

Both containers run without root, use read-only filesystems, drop Linux capabilities, expose health checks, and restart unless stopped. See [Docker deployment](docs/docker.md) for volumes, a domain proxy, health checks, and the optional LiteLLM sidecar.

## White-label settings

Edit [`site/config.js`](site/config.js):

```js
window.FLAGWATCH_CONFIG = {
  productName: "My CTF Calendar",
  organizationName: "My Security Club",
  shortDescription: "CTF schedules, rules, and cited source intelligence.",
  mark: "M",
  accentColor: "#006c7a",
  defaultTimeZone: "America/Chicago",
  logoUrl: "/logo.svg",
  faviconUrl: "/favicon.svg",
  footerLinks: [
    {label: "Source policy", url: "/source-policy"},
  ],
};
```

Brand URLs are restricted to safe public or same-site URLs. An accent color is applied only when white text meets the required contrast.

## Connectors and models

- [Event source connectors](docs/connectors.md)
- [OpenAI, Anthropic, DeepSeek, LiteLLM, and local models](docs/providers.md)
- [Collection and attribution policy](docs/source-policy.md)

The built-in parser works without a model. A model is an optional fallback for public event discovery and rules intelligence. Its output is rejected unless each evidence quote exists on the fetched source page.

## Native Python setup

Flagwatch requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run playwright install chromium
uv run flagwatch sync
uv run flagwatch serve
```

The private operator dashboard binds to `127.0.0.1:4814`. Syncing creates local alert previews but never sends them unless `FLAGWATCH_SEND_ENABLED=true` and a Discord webhook or complete SMTP destination is configured.

## Checks

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Browser tests run Axe, keyboard checks, and a 320 pixel layout check.

## License

MIT. See [LICENSE](LICENSE).
