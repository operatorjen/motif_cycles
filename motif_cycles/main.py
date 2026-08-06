from __future__ import annotations

import uvicorn

from .config import Settings


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "motif_cycles.api:create_app",
        host=settings.host,
        port=settings.port,
        factory=True,
        reload=False,
    )


if __name__ == "__main__":
    run()
