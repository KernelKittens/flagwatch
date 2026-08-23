# syntax=docker/dockerfile:1.7

FROM python:3.13-slim-bookworm AS python-build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/flagwatch/.venv
WORKDIR /build
RUN pip install --no-cache-dir uv==0.12.5
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim-bookworm AS sync

ENV PATH="/opt/flagwatch/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    FLAGWATCH_DATABASE_PATH=/data/state/flagwatch.db
RUN groupadd --gid 10001 flagwatch \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin flagwatch \
    && mkdir -p /opt/flagwatch /data/state /data/public \
    && chown -R 10001:10001 /opt/flagwatch /data
COPY --from=python-build --chown=10001:10001 /opt/flagwatch/.venv /opt/flagwatch/.venv
COPY --chown=10001:10001 docker/sync-loop.sh /usr/local/bin/flagwatch-sync-loop
COPY --chown=10001:10001 docker/healthcheck.py /opt/flagwatch/healthcheck.py
COPY --chown=10001:10001 docker/seed/events.json /data/public/events.json
RUN chmod 0555 /usr/local/bin/flagwatch-sync-loop /opt/flagwatch/healthcheck.py
USER 10001:10001
WORKDIR /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "/opt/flagwatch/healthcheck.py", "/data/public/events.json"]
ENTRYPOINT ["/usr/local/bin/flagwatch-sync-loop"]

FROM caddy:2.10.2-alpine AS web

RUN cp /usr/bin/caddy /usr/local/bin/caddy-unprivileged
COPY --chown=1000:1000 site /srv/site
COPY --chown=1000:1000 docker/seed/events.json /srv/data/events.json
COPY --chown=1000:1000 docker/Caddyfile /etc/caddy/Caddyfile
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/healthz"]
ENTRYPOINT ["caddy-unprivileged", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
