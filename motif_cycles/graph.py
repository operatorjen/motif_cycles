from __future__ import annotations

from typing import Any


def round_graph(round_record: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(
        node_id: str,
        kind: str,
        label: str,
        *,
        status: str = "waiting",
        optional: bool = False,
        detail: str = "",
    ) -> None:
        nodes.append(
            {
                "id": node_id,
                "kind": kind,
                "label": label,
                "status": status,
                "optional": optional,
                "detail": detail,
            }
        )

    def edge(source: str, target: str, relation: str, *, optional: bool = False) -> None:
        edges.append(
            {"source": source, "target": target, "relation": relation, "optional": optional}
        )

    parent_id = round_record.get("parent_round_id")
    if parent_id:
        node("parent", "lineage", "Earlier round", status="completed", detail=parent_id)
    node("inquiry", "human", "Human inquiry", status="completed", detail=round_record["inquiry"])
    if parent_id:
        edge("parent", "inquiry", "returns as")
    packet = round_record.get("motif_packet")
    node(
        "packet",
        "evidence",
        "Outcome trace" if parent_id else "Motif packet",
        status=(
            "completed"
            if packet
            else "running"
            if round_record["stage"] == "packet"
            else "waiting"
        ),
        detail=(packet or {}).get("artifact_id", ""),
    )
    edge("inquiry", "packet", "frames")
    progress = round_record.get("folding_progress") or {}
    operations = progress.get("operations") or []

    def operation_for(fragment: str) -> dict[str, Any] | None:
        return next(
            (item for item in operations if fragment in item.get("operation_key", "")),
            None,
        )

    def operation_detail(operation: dict[str, Any] | None) -> str:
        if not operation:
            return ""
        identity = " / ".join(
            value for value in (operation.get("provider"), operation.get("model")) if value
        )
        return operation.get("error") or identity

    for lens_id, label, operation_key in (
        ("embodied", "Phenomenological reading", "embodied"),
        ("cybernetic", "Cybernetic reading", "cybernetic"),
        ("infinite", "Infinite-game reading", "infinite_play"),
    ):
        operation = operation_for(operation_key)
        status = (
            "completed"
            if round_record.get("fold_artifact")
            else operation.get("status", "waiting")
            if operation
            else "waiting"
        )
        node(
            lens_id,
            "reading",
            label,
            status=status,
            detail=operation_detail(operation),
        )
        edge("packet", lens_id, "read by")
    fold_operation = operation_for("folds:final")
    folding_status = (
        "completed"
        if round_record.get("fold_artifact")
        else fold_operation.get("status", "waiting")
        if fold_operation
        else "waiting"
    )
    node(
        "folding",
        "transformation",
        "Fold field",
        status=folding_status,
        detail=operation_detail(fold_operation),
    )
    for lens_id in ("embodied", "cybernetic", "infinite"):
        edge(lens_id, "folding", "contributes")

    artifact = round_record.get("fold_artifact") or {}
    selected_id = round_record.get("selected_fold_id")
    for index, fold in enumerate(artifact.get("folds", []), start=1):
        fold_id = fold["id"]
        selected = fold_id == selected_id
        status = "selected" if selected else fold.get("disposition", "ready")
        node(
            fold_id,
            "option",
            f"{index}. {fold['title']}",
            status=status,
            optional=not selected,
            detail=fold.get("relation", ""),
        )
        edge("folding", fold_id, "opens", optional=not selected)

    if selected_id:
        node("decision", "human", "Human placement", status="completed")
        edge(selected_id, "decision", "selected")
        node(
            "experiment",
            "experiment",
            "Feedback experiment",
            status=(
                "completed"
                if round_record.get("feedback_trace")
                else "running"
                if round_record["stage"] == "experiment"
                else "waiting"
            ),
            detail=(round_record.get("contract") or {}).get("aim", ""),
        )
        edge("decision", "experiment", "enacts")
    if round_record.get("outcome"):
        node(
            "outcome",
            "return",
            "Outcome trace",
            status="completed",
            detail=round_record["outcome"].get("observation", ""),
        )
        edge("experiment", "outcome", "returns")
        node("artifact", "artifact", "Round Map", status="completed")
        edge("outcome", "artifact", "records")
    return {"nodes": nodes, "edges": edges}
