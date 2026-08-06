from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx


class ServiceError(RuntimeError):
    pass


class LocalServices:
    def __init__(self, feedback_url: str, folding_url: str, timeout: float = 600):
        self.feedback_url = feedback_url
        self.folding_url = folding_url
        self.client = httpx.Client(follow_redirects=False, trust_env=False, timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def _headers(self, url: str, supplied: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(supplied or {})
        if (
            url.startswith(f"{self.feedback_url}/")
            and urlparse(url).hostname == "host.docker.internal"
        ):
            # Feedback trusts loopback Host headers. Cycles reaches that same
            # loopback service through Docker's host alias.
            headers.setdefault("Host", "127.0.0.1")
        return headers

    def _request(self, method: str, url: str, **kwargs) -> Any:
        headers = self._headers(url, kwargs.pop("headers", None))
        try:
            response = self.client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ServiceError(f"Could not reach {url}: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ServiceError(f"{response.status_code} from {url}: {detail}")
        if not response.content:
            return None
        return response.json()

    def overview(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            feedback = self._request("GET", f"{self.feedback_url}/api/session")
            result["feedback"] = {
                "ok": True,
                "url": self.feedback_url,
                "projects": feedback.get("projects", []),
                "setup_complete": feedback.get("setup_complete", False),
            }
        except ServiceError as exc:
            result["feedback"] = {"ok": False, "url": self.feedback_url, "error": str(exc)}
        try:
            projects = self._request("GET", f"{self.folding_url}/api/projects")
            settings = self._request("GET", f"{self.folding_url}/api/settings")
            result["folding"] = {
                "ok": True,
                "url": self.folding_url,
                "projects": projects,
                "setup_complete": settings.get("setup_complete", False),
            }
        except ServiceError as exc:
            result["folding"] = {"ok": False, "url": self.folding_url, "error": str(exc)}
        return result

    def feedback_motifs(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"{self.feedback_url}/api/motifs/{project_id}")

    def _feedback_token(self) -> str:
        return self._request("GET", f"{self.feedback_url}/api/session")["token"]

    def create_motif_packet(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.feedback_url}/api/bridge/projects/{project_id}/motif-packets",
            json=payload,
            headers={"X-Motif-Token": self._feedback_token()},
        )

    def import_folding_artifact(
        self, project_id: str, title: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.folding_url}/api/bridge/projects/{project_id}/imports",
            json={"title": title, "payload": payload},
        )

    def start_folding_run(
        self, project_id: str, inquiry: str, source_id: str, round_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.folding_url}/api/projects/{project_id}/runs",
            json={
                "prompt": inquiry,
                "source_ids": [source_id],
                "external_round_id": round_id,
            },
        )

    def folding_artifact(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"{self.folding_url}/api/bridge/runs/{run_id}")

    def folding_status(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"{self.folding_url}/api/runs/{run_id}/status")

    def resume_folding_run(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"{self.folding_url}/api/runs/{run_id}/resume")

    def place_fold(self, fold_id: str, disposition: str) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"{self.folding_url}/api/folds/{fold_id}/disposition",
            json={"disposition": disposition},
        )

    def run_feedback_experiment(
        self,
        project_id: str,
        turn_id: str,
        message: str,
        participants: list[str],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.feedback_url}/api/chat",
            json={
                "turn_id": turn_id,
                "project_id": project_id,
                "message": message,
                "participants": participants,
                "research_mode": "off",
            },
            headers={"X-Motif-Token": self._feedback_token()},
        )

    def feedback_trace(self, project_id: str, turn_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"{self.feedback_url}/api/bridge/projects/{project_id}/turns/{turn_id}/trace",
        )

    def resume_feedback_experiment(self, project_id: str, turn_id: str) -> dict[str, Any]:
        url = f"{self.feedback_url}/api/chat-turns/{project_id}/{turn_id}/resume/stream"
        headers = self._headers(url, {"X-Motif-Token": self._feedback_token()})
        result: dict[str, Any] | None = None
        try:
            with self.client.stream("POST", url, headers=headers) as response:
                if response.status_code >= 400:
                    response.read()
                    try:
                        detail = response.json().get("detail", response.text)
                    except ValueError:
                        detail = response.text
                    raise ServiceError(f"{response.status_code} from {url}: {detail}")
                for line in response.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line.removeprefix("data: "))
                    if event.get("type") == "error":
                        raise ServiceError(str(event.get("detail") or "Feedback retry failed"))
                    if event.get("type") == "result":
                        result = event
        except httpx.HTTPError as exc:
            raise ServiceError(f"Could not reach {url}: {exc}") from exc
        if result is None:
            raise ServiceError("Feedback retry ended without a result")
        return result
