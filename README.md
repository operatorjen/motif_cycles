# Motif Cycles

Motif Cycles is the human-governed coordination layer between Motif Feedback and Motif Folding.
It turns an observer-owned motif packet into an attributed fold field, pauses for deliberate human
placement, returns the selected possibility to the Feedback room, and records the consequences as
a downloadable Round Map.

## One round

1. Choose a Feedback project and a Folding project.
2. Select motifs or checkpoints and state the relation to transform.
3. Watch the immutable packet pass through three parallel readings and the final fold.
4. Inspect every option, then select one and write its aim, scope, boundary, and stop condition.
5. Send the temporary experiment to the existing Feedback room.
6. Record the observed consequence, including surprise or contradiction.
7. Download the Markdown schematic or structured JSON record, or refold the outcome.

The live graph distinguishes the actual path, optional branches, human gates, and cross-round
returns. Unselected possibilities remain visible instead of being rewritten out of the history.

## Run locally

Start Motif Feedback on `127.0.0.1:8000` and Motif Folding on `127.0.0.1:8001`, complete their
normal model setup, then run:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
motif-cycles
```

Open [http://127.0.0.1:8002](http://127.0.0.1:8002). The connections at the top of the page report
whether both engines are reachable and configured.

The service URLs are configurable:

```bash
export MOTIF_FEEDBACK_URL=http://127.0.0.1:8000
export MOTIF_FOLDING_URL=http://127.0.0.1:8001
export MOTIF_CYCLES_WORKSPACE=workspace
motif-cycles
```

## Docker

When the two engines are already published on the host loopback interface:

```bash
cp .env.example .env
docker compose up -d --build
```

Open [http://127.0.0.1:8002](http://127.0.0.1:8002). The container reaches the two host services
through `host.docker.internal`. Edit `.env` only when an engine uses a different address, the
Cycles port should change, or bridge requests need a different timeout.

## Artifacts and ownership

Each round stores its own SQLite ledger under `workspace/` and exchanges versioned
`motif-bridge/v1` artifacts:

- `motif_packet`
- `fold_set`
- `return_contract`
- `execution_trace`
- `outcome_trace`
- `round_map`

Feedback remains authoritative for messages, agents, memories, motifs, evidence, and checkpoints.
Folding remains authoritative for sources, runs, readings, folds, placement, and fold lineage.
Cycles remains authoritative for cross-system decisions, experiment boundaries, outcome traces,
and the combined graph.

## Verification

```bash
python -m pytest -q -ra
ruff check .
node --check motif_cycles/static/app.js
docker compose config --quiet
```
