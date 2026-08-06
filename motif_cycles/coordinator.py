from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any

from .clients import LocalServices
from .export import outcome_artifact
from .storage import Storage


class RoundCoordinator:
    def __init__(self, storage: Storage, services: LocalServices):
        self.storage = storage
        self.services = services
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="motif-cycles")
        self.futures: dict[str, Future[None]] = {}
        self.lock = Lock()

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
        self.services.close()

    def start(self, round_id: str, packet_override: dict[str, Any] | None = None) -> None:
        with self.lock:
            active = self.futures.get(round_id)
            if active and not active.done():
                raise ValueError("That round is already running")
            future = self.executor.submit(self._start_fold, round_id, packet_override)
            self.futures[round_id] = future
        future.add_done_callback(lambda completed: self._forget(round_id, completed))

    def enact(self, round_id: str) -> None:
        with self.lock:
            active = self.futures.get(round_id)
            if active and not active.done():
                raise ValueError("That round is already running")
            future = self.executor.submit(self._run_experiment, round_id)
            self.futures[round_id] = future
        future.add_done_callback(lambda completed: self._forget(round_id, completed))

    def retry(self, round_id: str) -> dict[str, Any]:
        record = self.storage.get_round(round_id)
        if record["status"] != "failed":
            raise ValueError("Only a failed cycle can be re-run")
        with self.lock:
            active = self.futures.get(round_id)
            if active and not active.done():
                raise ValueError("That cycle is already running")
            self.storage.update_round(
                round_id,
                status="running",
                stage="retrying",
                error=None,
            )
            self.storage.add_event(
                round_id,
                "retry",
                f"Human requested a re-run from {record.get('failed_stage') or 'the failed stage'}",
            )
            future = self.executor.submit(self._retry_failed, round_id)
            self.futures[round_id] = future
        future.add_done_callback(lambda completed: self._forget(round_id, completed))
        return self.storage.get_round(round_id)

    def _forget(self, round_id: str, future: Future[None]) -> None:
        with self.lock:
            if self.futures.get(round_id) is future:
                self.futures.pop(round_id, None)

    def _retry_failed(self, round_id: str) -> None:
        try:
            record = self.storage.get_round(round_id)
            if record.get("feedback_turn_id") and not record.get("feedback_trace"):
                self.storage.update_round(round_id, status="running", stage="experiment")
                trace = self.services.feedback_trace(
                    record["feedback_project_id"], record["feedback_turn_id"]
                )
                turn_status = (trace.get("turn") or {}).get("status")
                if turn_status in {"failed", "interrupted"}:
                    self.storage.add_event(
                        round_id,
                        "experiment",
                        "Resuming the existing Feedback turn without duplicating completed work",
                    )
                    self.services.resume_feedback_experiment(
                        record["feedback_project_id"], record["feedback_turn_id"]
                    )
                    trace = self.services.feedback_trace(
                        record["feedback_project_id"], record["feedback_turn_id"]
                    )
                    turn_status = (trace.get("turn") or {}).get("status")
                if turn_status != "completed":
                    raise RuntimeError(f"Feedback turn is {turn_status or 'unavailable'}")
                self.storage.update_round(
                    round_id,
                    feedback_trace=trace,
                    status="waiting_human",
                    stage="closeout",
                    failed_stage=None,
                )
                self.storage.add_event(
                    round_id, "closeout", "Room returned after retry; awaiting human observation"
                )
                return

            if record.get("folding_run_id") and not record.get("fold_artifact"):
                self.storage.update_round(round_id, status="running", stage="folding")
                progress = self.services.folding_status(record["folding_run_id"])
                run_status = progress.get("status")
                if run_status == "completed":
                    artifact = self.services.folding_artifact(record["folding_run_id"])
                    self._accept_folding_artifact(round_id, artifact, retried=True)
                    return
                if run_status == "failed":
                    self.services.resume_folding_run(record["folding_run_id"])
                    self.storage.add_event(
                        round_id,
                        "folding",
                        "Existing Folding run resumed; completed operations will be reused",
                    )
                    return
                if run_status in {"queued", "running"}:
                    self.storage.add_event(
                        round_id, "folding", "Reattached to the existing Folding run"
                    )
                    return
                raise RuntimeError(f"Folding run is {run_status or 'unavailable'}")

            if record.get("folding_import"):
                self.storage.update_round(round_id, status="running", stage="folding")
                run = self.services.start_folding_run(
                    record["folding_project_id"],
                    record["inquiry"],
                    record["folding_import"]["source_id"],
                    round_id,
                )
                self.storage.update_round(round_id, folding_run_id=run["id"])
                self.storage.add_event(
                    round_id, "folding", "Folding restarted from the preserved bridge import"
                )
                return

            self._start_fold(round_id, record.get("motif_packet"))
        except Exception as exc:
            self._fail(round_id, exc)

    def _start_fold(self, round_id: str, packet_override: dict[str, Any] | None) -> None:
        try:
            record = self.storage.get_round(round_id)
            self.storage.update_round(round_id, status="running", stage="packet", error=None)
            self.storage.add_event(round_id, "packet", "Preparing an immutable bridge packet")
            packet = packet_override or self.services.create_motif_packet(
                record["feedback_project_id"],
                {
                    "motif_ids": record["motif_ids"],
                    "checkpoint_ids": record["checkpoint_ids"],
                    "inquiry": record["inquiry"],
                    "human_note": record["human_note"],
                },
            )
            self.storage.update_round(round_id, motif_packet=packet, stage="import")
            imported = self.services.import_folding_artifact(
                record["folding_project_id"],
                f"Round: {record['title']}",
                packet,
            )
            self.storage.update_round(round_id, folding_import=imported, stage="folding")
            self.storage.add_event(
                round_id, "folding", "Packet imported; three readings and final fold started"
            )
            run = self.services.start_folding_run(
                record["folding_project_id"],
                record["inquiry"],
                imported["source_id"],
                round_id,
            )
            self.storage.update_round(
                round_id,
                folding_run_id=run["id"],
                status="running",
                stage="folding",
            )
        except Exception as exc:
            self._fail(round_id, exc)

    def refresh(self, round_id: str) -> dict[str, Any]:
        record = self.storage.get_round(round_id)
        if (
            record["status"] == "failed"
            and record.get("folding_run_id")
            and not record.get("failure_trace")
        ):
            try:
                progress = self.services.folding_status(record["folding_run_id"])
                if progress.get("status") == "failed":
                    trace = self.services.folding_artifact(record["folding_run_id"])
                    record = self.storage.update_round(round_id, failure_trace=trace)
            except Exception:
                pass
        if record["stage"] != "folding" or not record.get("folding_run_id"):
            return record
        try:
            progress = self.services.folding_status(record["folding_run_id"])
        except Exception:
            return record
        if progress["status"] == "completed":
            try:
                artifact = self.services.folding_artifact(record["folding_run_id"])
            except Exception:
                return {**record, "folding_progress": progress}
            self._accept_folding_artifact(round_id, artifact)
        elif progress["status"] == "failed":
            try:
                artifact = self.services.folding_artifact(record["folding_run_id"])
            except Exception:
                artifact = None
            self._fail(
                round_id,
                RuntimeError(progress.get("error") or "Folding run failed"),
                trace=artifact,
            )
        refreshed = self.storage.get_round(round_id)
        if refreshed["stage"] == "folding":
            refreshed["folding_progress"] = progress
        return refreshed

    def _accept_folding_artifact(
        self, round_id: str, artifact: dict[str, Any], *, retried: bool = False
    ) -> None:
        self.storage.update_round(
            round_id,
            fold_artifact=artifact,
            status="waiting_human",
            stage="placement",
            failed_stage=None,
        )
        suffix = " after retry" if retried else ""
        self.storage.add_event(
            round_id,
            "placement",
            f"{len(artifact.get('folds', []))} folds ready for human placement{suffix}",
        )

    def select_fold(self, round_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.refresh(round_id)
        folds = (record.get("fold_artifact") or {}).get("folds", [])
        fold = next((item for item in folds if item["id"] == payload["fold_id"]), None)
        if fold is None:
            raise ValueError("Select a fold belonging to this round")
        self.services.place_fold(fold["id"], "continued")
        contract = {**payload, "fold_title": fold["title"], "fold_relation": fold["relation"]}
        result = self.storage.update_round(
            round_id,
            selected_fold_id=fold["id"],
            contract=contract,
            status="waiting_human",
            stage="contract",
        )
        self.storage.add_event(round_id, "contract", f"Human selected {fold['title']}")
        return result

    def _run_experiment(self, round_id: str) -> None:
        try:
            record = self.storage.get_round(round_id)
            if not record.get("contract") or not record.get("selected_fold_id"):
                raise ValueError("Choose a fold and complete its return contract first")
            turn_id = f"turn-{round_id.removeprefix('round-')}"
            contract = record["contract"]
            message = (
                f"ROUND EXPERIMENT {round_id}\n\n"
                f"Selected possibility: {contract['fold_title']}\n"
                f"Organizing relation: {contract['fold_relation']}\n\n"
                f"Aim: {contract['aim']}\n"
                f"Scope: {contract['scope']}\n"
                f"Stop condition: {contract['stop_condition']}\n"
                f"Protected boundary: {contract.get('protected_boundary') or 'None specified.'}\n\n"
                "Treat this as a temporary, human-authorized inquiry. Do not treat the fold as "
                "truth or as a persona update. Respond from your existing lens, notice what the "
                "proposed move reveals or fails to reveal, and preserve disagreement and "
                "uncertainty."
            )
            self.storage.update_round(
                round_id,
                status="running",
                stage="experiment",
                feedback_turn_id=turn_id,
            )
            self.storage.add_event(
                round_id,
                "experiment",
                "Human-authorized return sent to the room",
            )
            self.services.run_feedback_experiment(
                record["feedback_project_id"],
                turn_id,
                message,
                contract["participants"],
            )
            trace = self.services.feedback_trace(
                record["feedback_project_id"],
                turn_id,
            )
            self.storage.update_round(
                round_id,
                feedback_trace=trace,
                status="waiting_human",
                stage="closeout",
            )
            self.storage.add_event(
                round_id, "closeout", "Room returned; awaiting human observation"
            )
        except Exception as exc:
            self._fail(round_id, exc)

    def close_round(self, round_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.storage.get_round(round_id)
        if not record.get("feedback_trace"):
            raise ValueError("The Feedback experiment must return before closeout")
        self.services.place_fold(record["selected_fold_id"], payload["disposition"])
        self.storage.update_round(round_id, closeout=payload)
        updated = self.storage.get_round(round_id)
        outcome = outcome_artifact(updated)
        result = self.storage.update_round(
            round_id,
            outcome=outcome,
            status="completed",
            stage="completed",
        )
        self.storage.add_event(
            round_id, "completed", f"Round closed as {payload['disposition']}"
        )
        return self.storage.get_round(result["id"])

    def _fail(
        self, round_id: str, exc: Exception, *, trace: dict[str, Any] | None = None
    ) -> None:
        record = self.storage.get_round(round_id)
        values: dict[str, Any] = {
            "status": "failed",
            "stage": "failed",
            "failed_stage": record.get("stage"),
            "error": str(exc)[:4_000],
        }
        if trace is not None:
            values["failure_trace"] = trace
        self.storage.update_round(
            round_id,
            **values,
        )
        self.storage.add_event(round_id, "failed", str(exc)[:1_000])
