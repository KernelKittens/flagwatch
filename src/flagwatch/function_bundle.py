from __future__ import annotations

import shutil
from pathlib import Path


def build_function_bundle(project_root: Path, destination: Path) -> None:
    """Build the exact directory Azure Functions indexes at deployment."""
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Function bundle destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)

    function_root = project_root / "azure-functions"
    for filename in ("function_app.py", "host.json", "requirements.txt"):
        shutil.copy2(function_root / filename, destination / filename)
    shutil.copytree(project_root / "src" / "flagwatch", destination / "flagwatch")
