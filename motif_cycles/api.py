from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .clients import LocalServices, ServiceError
from .config import Settings
from .coordinator import RoundCoordinator
from .export import round_json, round_markdown
from .graph import round_graph
from .models import FoldSelection, RefoldRequest, RoundCloseout, RoundCreate
from .security import LocalGuard, LocalSecurityMiddleware
from .storage import Storage


def create_app(
    workspace: str | Path | None = None,
    services: LocalServices | None = None,
) -> FastAPI:
    settings = Settings.from_env(workspace)
    storage = Storage(settings.database)
    storage.initialize()
    local_services = services or LocalServices(
        settings.feedback_url,
        settings.folding_url,
        settings.request_timeout,
    )
    coordinator = RoundCoordinator(storage, local_services)
    guard = LocalGuard()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        coordinator.close()

    app = FastAPI(title="Motif Cycles", version="0.1.0", lifespan=lifespan)
    app.state.storage = storage
    app.state.coordinator = coordinator
    app.state.services = local_services
    app.state.guard = guard
    app.add_middleware(LocalSecurityMiddleware, guard=guard)
    app.mount("/assets", StaticFiles(directory=settings.static), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(settings.static / "index.html")

    @app.get("/api/session")
    def session() -> dict:
        return {
            "token": guard.token,
            "version": "0.1.0",
            "connections": local_services.overview(),
            "rounds": [_public_round(item) for item in storage.list_rounds()],
        }

    @app.get("/api/connections")
    def connections() -> dict:
        return local_services.overview()

    @app.get("/api/feedback/projects/{project_id}/motifs")
    def feedback_motifs(project_id: str) -> dict:
        try:
            return local_services.feedback_motifs(project_id)
        except ServiceError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/api/rounds")
    def rounds() -> list[dict]:
        return [_public_round(item) for item in storage.list_rounds()]

    @app.post("/api/rounds", status_code=202)
    def create_round(payload: RoundCreate) -> dict:
        record = storage.create_round(payload.model_dump())
        coordinator.start(record["id"])
        return _public_round(record)

    @app.get("/api/rounds/{round_id}")
    def round_detail(round_id: str) -> dict:
        try:
            return _public_round(coordinator.refresh(round_id))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/rounds/{round_id}/selection")
    def select_fold(round_id: str, payload: FoldSelection) -> dict:
        try:
            return _public_round(coordinator.select_fold(round_id, payload.model_dump()))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, ServiceError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/rounds/{round_id}/enact", status_code=202)
    def enact(round_id: str) -> dict:
        try:
            coordinator.enact(round_id)
            return _public_round(storage.get_round(round_id))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/rounds/{round_id}/retry", status_code=202)
    def retry_round(round_id: str) -> dict:
        try:
            return _public_round(coordinator.retry(round_id))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/rounds/{round_id}/close")
    def close_round(round_id: str, payload: RoundCloseout) -> dict:
        try:
            return _public_round(coordinator.close_round(round_id, payload.model_dump()))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, ServiceError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/rounds/{round_id}/refold", status_code=202)
    def refold(round_id: str, payload: RefoldRequest) -> dict:
        try:
            parent = storage.get_round(round_id)
            if not parent.get("outcome"):
                raise ValueError("Close the parent round before refolding its outcome")
            child = storage.create_round(
                {
                    "title": payload.title,
                    "inquiry": payload.inquiry,
                    "feedback_project_id": parent["feedback_project_id"],
                    "folding_project_id": parent["folding_project_id"],
                    "motif_ids": [],
                    "checkpoint_ids": [],
                    "human_note": "Outcome returned from an earlier round.",
                },
                parent_round_id=round_id,
            )
            coordinator.start(child["id"], parent["outcome"])
            return _public_round(child)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/rounds/{round_id}/map.md", response_class=PlainTextResponse)
    def export_markdown(round_id: str) -> PlainTextResponse:
        try:
            content = round_markdown(storage.get_round(round_id))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return PlainTextResponse(
            content,
            headers={"Content-Disposition": f'attachment; filename="{round_id}-map.md"'},
        )

    @app.get("/api/rounds/{round_id}/map.json", response_class=PlainTextResponse)
    def export_json(round_id: str) -> PlainTextResponse:
        try:
            content = round_json(_public_round(storage.get_round(round_id)))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return PlainTextResponse(
            content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{round_id}-map.json"'},
        )

    return app


def _public_round(record: dict) -> dict:
    return {**record, "graph": round_graph(record)}
