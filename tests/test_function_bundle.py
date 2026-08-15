from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flagwatch.function_bundle import build_function_bundle


def test_function_bundle_imports_from_isolated_artifact(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    bundle = tmp_path / "bundle"
    build_function_bundle(root, bundle)

    assert (bundle / "host.json").is_file()
    assert (bundle / "function_app.py").is_file()
    assert (bundle / "flagwatch" / "cloud_sync.py").is_file()
    command = (
        "import sys; "
        f"sys.path.insert(0, {str(bundle)!r}); "
        "import function_app; "
        "assert function_app.app is not None"
    )
    subprocess.run([sys.executable, "-I", "-c", command], check=True, cwd=tmp_path)
