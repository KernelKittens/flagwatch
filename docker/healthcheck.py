from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    path = Path(sys.argv[1])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 1
    if not isinstance(payload, dict):
        return 1
    if not isinstance(payload.get("generated_at"), str):
        return 1
    if not isinstance(payload.get("events"), list):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
