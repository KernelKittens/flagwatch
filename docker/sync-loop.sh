#!/bin/sh
set -eu

interval="${FLAGWATCH_SYNC_INTERVAL_SECONDS:-21600}"
case "$interval" in
  *[!0-9]*|'') echo "FLAGWATCH_SYNC_INTERVAL_SECONDS must be a positive integer" >&2; exit 2 ;;
esac
if [ "$interval" -lt 60 ]; then
  echo "FLAGWATCH_SYNC_INTERVAL_SECONDS must be at least 60" >&2
  exit 2
fi

refresh() {
  flagwatch refresh \
    --database "${FLAGWATCH_DATABASE_PATH:-/data/state/flagwatch.db}" \
    --output /data/public/events.json
}

if [ "${FLAGWATCH_SYNC_ONCE:-false}" = "true" ]; then
  exec flagwatch refresh \
    --database "${FLAGWATCH_DATABASE_PATH:-/data/state/flagwatch.db}" \
    --output /data/public/events.json
fi

trap 'exit 0' INT TERM
while :; do
  if ! refresh; then
    echo "Refresh failed. The last-good public snapshot is still active." >&2
  fi
  sleep "$interval" &
  wait "$!"
done
