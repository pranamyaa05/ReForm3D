"""Entry point script to start the ReForm3D server.

Validates configuration via :func:`reform3d.config.load_settings_for_startup` before
starting Uvicorn so missing or invalid environment variables fail fast with a clear,
actionable message.
"""

from __future__ import annotations

import sys

import uvicorn

from reform3d.config import ConfigurationError, load_settings_for_startup


def main() -> int:
    """Validate startup configuration and start Uvicorn."""
    try:
        settings = load_settings_for_startup()
    except ConfigurationError as exc:
        sys.stderr.write(f"\n[ERROR] {exc}\n\n")
        return 1

    uvicorn.run(
        "reform3d.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
