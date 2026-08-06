from __future__ import annotations

import json
import re
from typing import Any

from .graph import round_graph


def _mermaid_id(value: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", value)


def _mermaid_label(value: str) -> str:
    return str(value).replace('"', "'").replace("\n", " ")[:100]


def mermaid_graph(round_record: dict[str, Any]) -> str:
    graph = round_graph(round_record)
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        lines.append(f'    {_mermaid_id(node["id"])}["{_mermaid_label(node["label"])}"]')
    for edge in graph["edges"]:
        arrow = "-.->" if edge["optional"] else "-->"
        lines.append(
            f'    {_mermaid_id(edge["source"])} {arrow}|"{_mermaid_label(edge["relation"])}"| '
            f'{_mermaid_id(edge["target"])}'
        )
    return "\n".join(lines)


def round_markdown(round_record: dict[str, Any]) -> str:
    lines = [
        f"# Round Map: {round_record['title']}",
        "",
        f"- Round ID: `{round_record['id']}`",
        f"- Status: `{round_record['status']}`",
        f"- Created: {round_record['created_at']}",
        f"- Parent round: `{round_record.get('parent_round_id') or 'none'}`",
        "",
        "## Inquiry",
        "",
        round_record["inquiry"],
        "",
        "## Schematic",
        "",
        "```mermaid",
        mermaid_graph(round_record),
        "```",
        "",
    ]
    packet = round_record.get("motif_packet") or {}
    if packet:
        lines.extend(["## Input packet", ""])
        for motif in packet.get("motifs", []):
            lines.append(
                f"- **{motif.get('label', 'Untitled')}** — "
                f"{motif.get('observer_agent_id', 'unknown')} / {motif.get('status', 'unknown')}"
            )
        if not packet.get("motifs"):
            lines.append(f"- `{packet.get('artifact_type', 'artifact')}` from earlier round")
        lines.append("")
    failure_trace = round_record.get("failure_trace") or {}
    if failure_trace.get("operations"):
        lines.extend(["## Failed attempt trace", ""])
        for operation in failure_trace["operations"]:
            identity = " / ".join(
                str(value)
                for value in (operation.get("provider"), operation.get("model"))
                if value
            )
            detail = f" — {identity}" if identity else ""
            lines.append(
                f"- **{operation.get('operation_key', 'operation')}**: "
                f"`{operation.get('status', 'unknown')}`{detail}"
            )
            if operation.get("error"):
                lines.append(f"  - Error: {operation['error']}")
        lines.append("")
    artifact = round_record.get("fold_artifact") or {}
    if artifact.get("folds"):
        lines.extend(["## Optionality", ""])
        for fold in artifact["folds"]:
            selected = (
                " — **selected**"
                if fold["id"] == round_record.get("selected_fold_id")
                else ""
            )
            lines.extend(
                [
                    f"### {fold['title']}{selected}",
                    "",
                    fold.get("relation", ""),
                    "",
                    fold.get("artifact", ""),
                    "",
                ]
            )
    if round_record.get("contract"):
        contract = round_record["contract"]
        lines.extend(
            [
                "## Return contract",
                "",
                f"- Aim: {contract['aim']}",
                f"- Scope: {contract['scope']}",
                f"- Stop condition: {contract['stop_condition']}",
                f"- Protected boundary: {contract.get('protected_boundary') or 'None recorded'}",
                "",
            ]
        )
    if round_record.get("outcome"):
        outcome = round_record["outcome"]
        lines.extend(
            [
                "## Outcome trace",
                "",
                outcome["observation"],
                "",
                f"- Surprise: {outcome.get('surprise') or 'None recorded'}",
                f"- Contradiction: {outcome.get('contradiction') or 'None recorded'}",
                f"- Human report: {outcome.get('human_report') or 'None recorded'}",
                f"- Placement: `{outcome['disposition']}`",
                "",
            ]
        )
    lines.extend(["## Event ledger", ""])
    for event in round_record["events"]:
        lines.append(f"- {event['created_at']} — **{event['stage']}**: {event['message']}")
    lines.extend(
        [
            "",
            "## Structured record",
            "",
            "The accompanying JSON export preserves the complete re-importable round record.",
            "",
        ]
    )
    return "\n".join(lines)


def outcome_artifact(round_record: dict[str, Any]) -> dict[str, Any]:
    closeout = round_record["closeout"]
    return {
        "schema_version": "motif-bridge/v1",
        "artifact_type": "outcome_trace",
        "artifact_id": f"outcome_{round_record['id']}",
        "source_system": "motif_cycles",
        "round_id": round_record["id"],
        "parent_artifact_ids": [
            item
            for item in (
                (round_record.get("motif_packet") or {}).get("artifact_id"),
                (round_record.get("fold_artifact") or {}).get("artifact_id"),
            )
            if item
        ],
        "selected_fold_id": round_record["selected_fold_id"],
        "return_contract": round_record["contract"],
        "observation": closeout["observation"],
        "surprise": closeout["surprise"],
        "contradiction": closeout["contradiction"],
        "human_report": closeout["human_report"],
        "disposition": closeout["disposition"],
        "feedback_trace": round_record.get("feedback_trace"),
    }


def round_json(round_record: dict[str, Any]) -> str:
    return json.dumps(round_record, ensure_ascii=False, indent=2) + "\n"
