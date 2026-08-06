from __future__ import annotations

import time
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from motif_cycles.api import create_app
from motif_cycles.clients import LocalServices


class FakeServices:
    def __init__(self, *, fail_folding: bool = False, folding_state: str | None = None):
        self.placements: list[tuple[str, str]] = []
        self.folding_state = folding_state or ("failed" if fail_folding else "completed")
        self.folding_resume_calls = 0
        self.folding_artifact_calls = 0

    def close(self) -> None:
        pass

    def overview(self) -> dict:
        return {
            "feedback": {
                "ok": True,
                "setup_complete": True,
                "projects": [{"id": "feedback-one", "name": "Feedback field"}],
            },
            "folding": {
                "ok": True,
                "setup_complete": True,
                "projects": [{"id": "folding-one", "name": "Folding field"}],
            },
        }

    def feedback_motifs(self, project_id: str) -> dict:
        return {"project_id": project_id, "motifs": [], "checkpoints": []}

    def create_motif_packet(self, project_id: str, payload: dict) -> dict:
        return {
            "schema_version": "motif-bridge/v1",
            "artifact_type": "motif_packet",
            "artifact_id": "packet-fake",
            "source_system": "motif_feedback",
            "project": {"id": project_id, "name": "Feedback field"},
            "inquiry": payload["inquiry"],
            "motifs": [],
            "checkpoints": [],
        }

    def import_folding_artifact(self, project_id: str, title: str, payload: dict) -> dict:
        return {"artifact_id": payload["artifact_id"], "source_id": "source-fake"}

    def start_folding_run(
        self, project_id: str, inquiry: str, source_id: str, round_id: str
    ) -> dict:
        return {"id": "run-fake", "status": "queued"}

    def folding_artifact(self, run_id: str) -> dict:
        self.folding_artifact_calls += 1
        if self.folding_state == "failed":
            return {
                "schema_version": "motif-bridge/v1",
                "artifact_type": "execution_trace",
                "artifact_id": "folding-failed",
                "run": {
                    "id": run_id,
                    "status": "failed",
                    "stage": "failed",
                    "error": "Reader request timed out",
                },
                "events": [
                    {"stage": "reading", "message": "Running three readings"},
                    {"stage": "failed", "message": "Reader request timed out"},
                ],
                "operations": [
                    {
                        "operation_key": "conversation:0:embodied",
                        "status": "completed",
                        "provider": "openai",
                        "model": "test-model",
                    },
                    {
                        "operation_key": "conversation:1:cybernetic",
                        "status": "failed",
                        "provider": "gemini",
                        "model": "test-model",
                        "error": "Reader request timed out",
                    },
                ],
                "folds": [],
            }
        return {
            "schema_version": "motif-bridge/v1",
            "artifact_type": "fold_set",
            "artifact_id": "folding-fake",
            "run": {"id": run_id, "status": "completed", "stage": "completed"},
            "folds": [
                {
                    "id": "fold-one",
                    "title": "Reversible opening",
                    "relation": "A reversible move tests the boundary.",
                    "artifact": "Try the move without making it permanent.",
                    "disposition": "ready",
                },
                {
                    "id": "fold-two",
                    "title": "Hold the difference",
                    "relation": "Keep both accounts available.",
                    "artifact": "Do not choose too early.",
                    "disposition": "ready",
                },
            ],
        }

    def folding_status(self, run_id: str) -> dict:
        operation_status = "completed" if self.folding_state == "completed" else self.folding_state
        return {
            "id": run_id,
            "prompt": "What returns?",
            "status": self.folding_state,
            "stage": "completed" if self.folding_state == "completed" else "reading",
            "error": "Reader request timed out" if self.folding_state == "failed" else None,
            "created_at": "2026-08-06T00:00:00+00:00",
            "completed_at": None,
            "operations": [
                {
                    "operation_key": "conversation:0:embodied",
                    "status": operation_status,
                    "provider": "openai",
                    "model": "test-model",
                    "error": None,
                    "started_at": "2026-08-06T00:00:00+00:00",
                    "completed_at": None,
                }
            ],
            "events": [{"stage": "reading", "message": "Running three readings"}],
        }

    def resume_folding_run(self, run_id: str) -> dict:
        self.folding_resume_calls += 1
        self.folding_state = "completed"
        return {"id": run_id, "status": "queued"}

    def place_fold(self, fold_id: str, disposition: str) -> dict:
        self.placements.append((fold_id, disposition))
        return {"id": fold_id, "disposition": disposition}

    def run_feedback_experiment(
        self, project_id: str, turn_id: str, message: str, participants: list[str]
    ) -> dict:
        return {"turn_id": turn_id, "status": "completed"}

    def feedback_trace(self, project_id: str, turn_id: str) -> dict:
        return {
            "schema_version": "motif-bridge/v1",
            "artifact_type": "execution_trace",
            "artifact_id": "trace-fake",
            "turn": {"id": turn_id, "status": "completed"},
            "operations": [],
            "messages": [
                {"role": "agent", "agent_id": "agent_a", "content": "A return."}
            ],
        }

    def resume_feedback_experiment(self, project_id: str, turn_id: str) -> dict:
        return {"turn_id": turn_id, "status": "completed"}


def auth(client: TestClient) -> dict[str, str]:
    token = client.get("/api/session").json()["token"]
    return {"X-Motif-Cycles-Token": token}


def wait_for(client: TestClient, round_id: str, stage: str, timeout: float = 2) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = client.get(f"/api/rounds/{round_id}").json()
        if record["stage"] == stage:
            return record
        time.sleep(0.01)
    raise AssertionError(f"round did not reach {stage}")


def test_complete_round_and_refold_preserve_graph_and_artifacts(tmp_path: Path) -> None:
    services = FakeServices()
    with TestClient(create_app(tmp_path, services)) as client:
        headers = auth(client)
        created = client.post(
            "/api/rounds",
            headers=headers,
            json={
                "title": "Threshold experiment",
                "inquiry": "What move reveals the boundary?",
                "feedback_project_id": "feedback-one",
                "folding_project_id": "folding-one",
            },
        )
        assert created.status_code == 202
        round_id = created.json()["id"]
        ready = wait_for(client, round_id, "placement")
        assert len(ready["fold_artifact"]["folds"]) == 2
        assert any(node["kind"] == "option" for node in ready["graph"]["nodes"])

        selected = client.post(
            f"/api/rounds/{round_id}/selection",
            headers=headers,
            json={
                "fold_id": "fold-one",
                "aim": "See whether a reversible move changes the relation.",
                "scope": "One room turn.",
                "stop_condition": "Stop after all selected agents return.",
                "participants": ["agent_a", "agent_b"],
            },
        )
        assert selected.status_code == 200
        assert selected.json()["stage"] == "contract"
        assert services.placements[-1] == ("fold-one", "continued")

        enacted = client.post(f"/api/rounds/{round_id}/enact", headers=headers)
        assert enacted.status_code == 202
        wait_for(client, round_id, "closeout")
        closed = client.post(
            f"/api/rounds/{round_id}/close",
            headers=headers,
            json={
                "observation": "The boundary became discussable without disappearing.",
                "surprise": "The second agent resisted the proposed framing.",
                "contradiction": "No behavioral change has been established.",
                "human_report": "The room felt less closed.",
                "disposition": "held",
            },
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "completed"
        assert closed.json()["outcome"]["artifact_type"] == "outcome_trace"
        assert any(node["id"] == "artifact" for node in closed.json()["graph"]["nodes"])

        markdown = client.get(f"/api/rounds/{round_id}/map.md")
        assert "```mermaid" in markdown.text
        assert "Optionality" in markdown.text
        assert "Outcome trace" in markdown.text

        child = client.post(
            f"/api/rounds/{round_id}/refold",
            headers=headers,
            json={"title": "Returned boundary", "inquiry": "What transformed?"},
        )
        assert child.status_code == 202
        assert child.json()["parent_round_id"] == round_id
        child_ready = wait_for(client, child.json()["id"], "placement")
        assert child_ready["motif_packet"]["artifact_type"] == "outcome_trace"


def test_mutations_require_local_token(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path, FakeServices())) as client:
        response = client.post(
            "/api/rounds",
            json={
                "title": "Blocked",
                "inquiry": "Should not start",
                "feedback_project_id": "feedback-one",
                "folding_project_id": "folding-one",
            },
        )
    assert response.status_code == 403


def test_failed_folding_run_can_resume_without_recreating_the_cycle(tmp_path: Path) -> None:
    services = FakeServices(fail_folding=True)
    with TestClient(create_app(tmp_path, services)) as client:
        headers = auth(client)
        created = client.post(
            "/api/rounds",
            headers=headers,
            json={
                "title": "Recoverable cycle",
                "inquiry": "What survives a provider timeout?",
                "feedback_project_id": "feedback-one",
                "folding_project_id": "folding-one",
            },
        )
        round_id = created.json()["id"]
        failed = wait_for(client, round_id, "failed")

        assert failed["failed_stage"] == "folding"
        assert failed["failure_trace"]["operations"][0]["status"] == "completed"

        retried = client.post(f"/api/rounds/{round_id}/retry", headers=headers)
        assert retried.status_code == 202
        ready = wait_for(client, round_id, "placement")

        assert ready["id"] == round_id
        assert services.folding_resume_calls == 1
        assert any(event["stage"] == "retry" for event in ready["events"])
        assert len(ready["fold_artifact"]["folds"]) == 2

        duplicate = client.post(f"/api/rounds/{round_id}/retry", headers=headers)
        assert duplicate.status_code == 409


def test_running_fold_poll_uses_lightweight_progress_without_fetching_artifact(
    tmp_path: Path,
) -> None:
    services = FakeServices(folding_state="running")
    with TestClient(create_app(tmp_path, services)) as client:
        headers = auth(client)
        created = client.post(
            "/api/rounds",
            headers=headers,
            json={
                "title": "Visible cycle",
                "inquiry": "What is happening now?",
                "feedback_project_id": "feedback-one",
                "folding_project_id": "folding-one",
            },
        )
        record = wait_for(client, created.json()["id"], "folding")

        assert record["folding_progress"]["stage"] == "reading"
        assert record["folding_progress"]["operations"][0]["status"] == "running"
        assert services.folding_artifact_calls == 0


def test_feedback_bridge_preserves_loopback_host_trust_from_docker() -> None:
    observed_feedback_host = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_feedback_host
        if request.url.host == "host.docker.internal" and request.url.port == 8000:
            observed_feedback_host = request.headers.get("host")
            return httpx.Response(
                200,
                json={
                    "projects": [{"id": "feedback-one", "name": "Feedback field"}],
                    "setup_complete": True,
                },
            )
        if request.url.path == "/api/projects":
            return httpx.Response(200, json=[])
        if request.url.path == "/api/settings":
            return httpx.Response(200, json={"setup_complete": True})
        raise AssertionError(f"Unexpected request: {request.url}")

    services = LocalServices(
        "http://host.docker.internal:8000",
        "http://host.docker.internal:8001",
    )
    services.client.close()
    services.client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        overview = services.overview()
    finally:
        services.close()

    assert observed_feedback_host == "127.0.0.1"
    assert overview["feedback"]["projects"][0]["id"] == "feedback-one"
