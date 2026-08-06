from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    workspace: Path
    feedback_url: str
    folding_url: str
    host: str
    port: int
    request_timeout: float

    @classmethod
    def from_env(cls, workspace: str | Path | None = None) -> Settings:
        root = Path(
            workspace
            or os.environ.get("MOTIF_CYCLES_WORKSPACE", "workspace")
        ).expanduser().resolve()
        return cls(
            workspace=root,
            feedback_url=os.environ.get(
                "MOTIF_FEEDBACK_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
            folding_url=os.environ.get(
                "MOTIF_FOLDING_URL", "http://127.0.0.1:8001"
            ).rstrip("/"),
            host=os.environ.get("MOTIF_CYCLES_HOST", "127.0.0.1"),
            port=int(os.environ.get("MOTIF_CYCLES_PORT", "8002")),
            request_timeout=float(os.environ.get("MOTIF_CYCLES_TIMEOUT_SECONDS", "600")),
        )

    @property
    def database(self) -> Path:
        return self.workspace / "rounds.db"

    @property
    def static(self) -> Path:
        return Path(__file__).resolve().parent / "static"
