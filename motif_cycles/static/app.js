const state = { token: "", session: null, current: null, motifs: null, polling: null };
const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  if (options.method && options.method !== "GET") headers["X-Motif-Cycles-Token"] = state.token;
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function escapeText(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function notify(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.remove("hidden");
  window.setTimeout(() => notice.classList.add("hidden"), 4500);
}

function statusLabel(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

async function initialize() {
  state.session = await api("/api/session");
  state.token = state.session.token;
  renderConnections(state.session.connections);
  populateProjects(state.session.connections);
  renderRoundList(state.session.rounds);
  const first = state.session.rounds[0];
  if (first) await openRound(first.id);
}

function renderConnections(connections) {
  $("#connections").innerHTML = ["feedback", "folding"].map((key) => {
    const item = connections[key] || {};
    const setup = item.ok && !item.setup_complete ? " · setup needed" : "";
    return `<span class="connection ${item.ok ? "ok" : "bad"}">${escapeText(key)}${setup}</span>`;
  }).join("");
}

function populateProjects(connections) {
  const pairs = [
    ["#feedback-project", connections.feedback?.projects || []],
    ["#folding-project", connections.folding?.projects || []],
  ];
  pairs.forEach(([selector, projects]) => {
    const select = $(selector);
    select.replaceChildren();
    projects.forEach((project) => {
      const option = document.createElement("option");
      option.value = project.id;
      option.textContent = project.name;
      select.append(option);
    });
  });
  if (connections.feedback?.projects?.length) loadMotifs(connections.feedback.projects[0].id);
}

async function loadMotifs(projectId) {
  try {
    state.motifs = await api(`/api/feedback/projects/${encodeURIComponent(projectId)}/motifs`);
    renderSelections();
  } catch (error) {
    $("#motif-options").innerHTML = `<span class="empty">${escapeText(error.message)}</span>`;
  }
}

function renderSelections() {
  const motifs = state.motifs?.motifs || [];
  $("#motif-options").innerHTML = motifs.length ? motifs.map((motif) => `
    <label class="check-option"><input type="checkbox" name="motif_ids" value="${escapeText(motif.id)}">
      <span>${escapeText(motif.label)}<small>${escapeText(motif.observer_agent_id)} · ${escapeText(motif.status)}</small></span>
    </label>`).join("") : `<span class="empty">No motifs recorded yet; the inquiry can still be folded.</span>`;
  const checkpoints = state.motifs?.checkpoints || [];
  $("#checkpoint-options").innerHTML = checkpoints.length ? checkpoints.map((item) => `
    <label class="check-option"><input type="checkbox" name="checkpoint_ids" value="${escapeText(item.id)}">
      <span>${escapeText((item.labels || []).join(" → "))}<small>checkpoint · ${escapeText(item.preference)}</small></span>
    </label>`).join("") : "";
}

function renderRoundList(rounds) {
  const container = $("#round-list");
  container.innerHTML = rounds.length ? rounds.map((round) => `
    <button type="button" class="round-item ${state.current?.id === round.id ? "active" : ""}" data-round="${round.id}">
      <strong>${escapeText(round.title)}</strong><small>${escapeText(statusLabel(round.status))}</small>
    </button>`).join("") : `<span class="empty">No rounds yet.</span>`;
  container.querySelectorAll("[data-round]").forEach((button) => {
    button.addEventListener("click", () => openRound(button.dataset.round));
  });
}

async function refreshRoundList() {
  const rounds = await api("/api/rounds");
  renderRoundList(rounds);
}

async function openRound(roundId) {
  state.current = await api(`/api/rounds/${roundId}`);
  $("#round-form").classList.add("hidden");
  $("#active-step").classList.remove("hidden");
  renderCurrent();
  await refreshRoundList();
  managePolling();
}

function renderCurrent() {
  const round = state.current;
  $("#map-title").textContent = round.title;
  renderGraph(round.graph);
  renderAnalysis(round);
  renderMapActions(round);
  renderActiveStep(round);
}

function renderMapActions(round) {
  $("#map-actions").innerHTML = `
    <button type="button" id="map-focus">${document.body.classList.contains("map-focus") ? "SHOW WORKFLOW" : "FOCUS MAP"}</button>
    <a href="/api/rounds/${round.id}/map.md">DOWNLOAD MAP</a>
    <a href="/api/rounds/${round.id}/map.json">DOWNLOAD DATA</a>`;
  $("#map-focus").addEventListener("click", () => {
    document.body.classList.toggle("map-focus");
    renderMapActions(round);
  });
}

function renderAnalysis(round) {
  const folds = round.fold_artifact?.folds || [];
  const selected = round.selected_fold_id ? 1 : 0;
  const returns = round.feedback_trace?.messages?.filter((message) => message.role === "agent").length || 0;
  $("#analysis").innerHTML = [
    [round.motif_packet?.motifs?.length || 0, "motifs carried"],
    [folds.length, "options opened"],
    [selected, "human placements"],
    [returns, "room returns"],
  ].map(([value, label]) => `<span class="analysis-item"><strong>${value}</strong><small>${label}</small></span>`).join("");
}

function renderActiveStep(round) {
  const panel = $("#active-step");
  if (round.status === "failed") {
    panel.innerHTML = `<div class="step-heading"><span>!</span><div><strong>Cycle stopped</strong><small>Completed operations remain available and will be reused.</small></div></div>
      <div class="status-line failed">${escapeText(round.error)}</div>
      ${failureTrace(round)}
      <button id="retry-cycle" type="button" class="primary">RE-RUN CYCLE</button>
      ${eventLedger(round, 12, false)}`;
    $("#retry-cycle").addEventListener("click", retryCycle);
    return;
  }
  if (["intake", "packet", "import", "folding", "retrying"].includes(round.stage)) {
    const liveStage = round.folding_progress?.stage || round.stage;
    panel.innerHTML = `<div class="step-heading"><span>2</span><div><strong>Transforming the field</strong><small>The map updates as the packet moves through the readers.</small></div></div><div class="status-line">Current stage: ${escapeText(statusLabel(liveStage))}</div>${liveExecution(round)}${eventLedger(round)}`;
    return;
  }
  if (round.stage === "placement") {
    const folds = round.fold_artifact?.folds || [];
    panel.innerHTML = `<form id="selection-form">
      <div class="step-heading"><span>3</span><div><strong>Choose a possibility</strong><small>Unchosen folds remain visible; selecting does not make one true.</small></div></div>
      <div class="fold-options">${folds.map((fold, index) => `<label class="fold-option"><span><input type="radio" name="fold_id" value="${fold.id}" ${index === 0 ? "required" : ""}> <strong>${escapeText(fold.title)}</strong></span><p>${escapeText(fold.relation)}</p></label>`).join("")}</div>
      <label>Aim<textarea name="aim" rows="2" required placeholder="What should this move reveal or change?"></textarea></label>
      <label>Scope<input name="scope" required placeholder="Where and for how long does this apply?"></label>
      <label>Stop condition<input name="stop_condition" required placeholder="When should this experiment stop?"></label>
      <label>Protected boundary <span class="optional">optional</span><input name="protected_boundary" placeholder="What must not be altered?"></label>
      <fieldset class="selection-block"><legend>Room participants</legend>${["agent_a", "agent_b", "agent_c"].map((id) => `<label class="check-option ${id.replace("agent_", "agent-")}"><input type="checkbox" name="participants" value="${id}" checked><span>${id.replace("agent_", "Agent ").toUpperCase()}</span></label>`).join("")}</fieldset>
      <button type="submit" class="primary">CREATE RETURN CONTRACT</button>
    </form>`;
    panel.querySelectorAll(".fold-option input").forEach((input) => input.addEventListener("change", () => {
      panel.querySelectorAll(".fold-option").forEach((item) => item.classList.toggle("selected", item.contains(input) && input.checked));
    }));
    $("#selection-form").addEventListener("submit", submitSelection);
    return;
  }
  if (round.stage === "contract") {
    panel.innerHTML = `<div class="step-heading"><span>4</span><div><strong>Enact the return</strong><small>The fold enters Feedback as a temporary, human-authorized inquiry.</small></div></div>
      <div class="status-line"><strong>${escapeText(round.contract.fold_title)}</strong><br>${escapeText(round.contract.aim)}</div>
      <p class="optional">Scope: ${escapeText(round.contract.scope)}<br>Stop: ${escapeText(round.contract.stop_condition)}</p>
      <button id="enact" type="button" class="primary">SEND TO FEEDBACK</button>`;
    $("#enact").addEventListener("click", enactRound);
    return;
  }
  if (round.stage === "experiment") {
    panel.innerHTML = `<div class="step-heading"><span>4</span><div><strong>Feedback experiment running</strong><small>The selected agents are responding in their normal sequential room order.</small></div></div><div class="status-line">Waiting for the room return…</div>${eventLedger(round)}`;
    return;
  }
  if (round.stage === "closeout") {
    panel.innerHTML = `<form id="close-form">
      <div class="step-heading"><span>5</span><div><strong>Record what happened</strong><small>Your observation closes the loop; null and contradictory results count.</small></div></div>
      <label>Observed consequence<textarea name="observation" rows="4" required placeholder="What actually changed, persisted, or became visible?"></textarea></label>
      <label>Surprise <span class="optional">optional</span><textarea name="surprise" rows="2"></textarea></label>
      <label>Contradiction <span class="optional">optional</span><textarea name="contradiction" rows="2"></textarea></label>
      <label>Human report <span class="optional">optional</span><textarea name="human_report" rows="2" placeholder="What mattered or felt different beyond the recorded responses?"></textarea></label>
      <label>Placement<select name="disposition"><option value="continued">Continue</option><option value="held">Hold</option><option value="retired">Retire</option></select></label>
      <button type="submit" class="primary">CLOSE ROUND</button>
    </form>`;
    $("#close-form").addEventListener("submit", submitCloseout);
    return;
  }
  if (round.stage === "completed") {
    panel.innerHTML = `<div class="step-heading"><span>✓</span><div><strong>Round mapped</strong><small>The selected path and unchosen possibilities remain inspectable.</small></div></div>
      <div class="status-line">Closed as ${escapeText(round.outcome.disposition)}. Download the map or return this outcome for another fold.</div>
      <form id="refold-form"><label>Next inquiry<textarea name="inquiry" rows="3" required placeholder="What should the returned outcome transform next?"></textarea></label><label>Next round title<input name="title" required value="Return from ${escapeText(round.title)}"></label><button type="submit" class="secondary">REFOLD OUTCOME</button></form>`;
    $("#refold-form").addEventListener("submit", submitRefold);
  }
}

function eventLedger(round, limit = 4, newestFirst = true) {
  const selected = round.events.slice(-limit);
  if (newestFirst) selected.reverse();
  return `<div class="selection-block event-ledger"><strong>Execution ledger</strong>${selected.map((event) => `<small><strong>${escapeText(statusLabel(event.stage))}</strong> — ${escapeText(event.message)}</small>`).join("")}</div>`;
}

function durationLabel(startedAt, completedAt) {
  if (!startedAt || !completedAt) return "";
  const milliseconds = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "";
  return milliseconds < 1000 ? `${milliseconds}ms` : `${(milliseconds / 1000).toFixed(1)}s`;
}

function operationName(operation) {
  const key = String(operation.operation_key || "operation");
  if (key.includes("embodied")) return "Embodied reading";
  if (key.includes("cybernetic")) return "Cybernetic reading";
  if (key.includes("infinite_play")) return "Infinite-game reading";
  if (key === "folds:final") return "Final folding";
  return statusLabel(key.replaceAll(":", " "));
}

function operationLensClass(operation) {
  const key = String(operation.operation_key || "");
  if (key.includes("embodied")) return "lens-phenomenological";
  if (key.includes("cybernetic")) return "lens-cybernetic";
  if (key.includes("infinite_play")) return "lens-infinite";
  return "";
}

function failureTrace(round) {
  const trace = round.failure_trace || {};
  const operations = trace.operations || [];
  if (!operations.length) return `<p class="optional">The event ledger records the last completed stage. Re-running will resume from the safest preserved artifact.</p>`;
  const completed = operations.filter((operation) => operation.status === "completed").length;
  const failed = operations.filter((operation) => operation.status === "failed").length;
  return `<section class="execution-trace">
    <div class="trace-summary"><strong>${completed} COMPLETED</strong><strong>${failed} FAILED</strong><span>${operations.length} OPERATIONS</span></div>
    <div class="trace-operations">${operations.map((operation) => {
      const duration = durationLabel(operation.started_at, operation.completed_at);
      const identity = [operation.provider, operation.model].filter(Boolean).join(" / ");
      return `<div class="trace-operation ${escapeText(operation.status)} ${operationLensClass(operation)}"><span class="trace-state">${operation.status === "completed" ? "✓" : operation.status === "failed" ? "!" : "·"}</span><div><strong>${escapeText(operationName(operation))}</strong><small>${escapeText([identity, duration].filter(Boolean).join(" · "))}</small>${operation.error ? `<small class="trace-error">${escapeText(operation.error)}</small>` : ""}</div></div>`;
    }).join("")}</div>
    <p>Re-running preserves completed operations and retries the failed step.</p>
  </section>`;
}

function liveExecution(round) {
  const progress = round.folding_progress || {};
  const operations = progress.operations || [];
  if (!operations.length) return `<p class="optional">Preparing the readers. Live operation detail will appear here.</p>`;
  const counts = operations.reduce((result, operation) => {
    result[operation.status] = (result[operation.status] || 0) + 1;
    return result;
  }, {});
  return `<section class="execution-trace live-trace">
    <div class="trace-summary"><strong>${counts.completed || 0} COMPLETED</strong><strong>${counts.running || 0} RUNNING</strong><span>${operations.length} OPERATIONS</span></div>
    <div class="trace-operations">${operations.map((operation) => {
      const duration = durationLabel(operation.started_at, operation.completed_at || new Date().toISOString());
      const identity = [operation.provider, operation.model].filter(Boolean).join(" / ");
      const symbol = operation.status === "completed" ? "✓" : operation.status === "failed" ? "!" : "·";
      return `<div class="trace-operation ${escapeText(operation.status)} ${operationLensClass(operation)}"><span class="trace-state">${symbol}</span><div><strong>${escapeText(operationName(operation))}</strong><small>${escapeText([identity, operation.status, duration].filter(Boolean).join(" · "))}</small>${operation.error ? `<small class="trace-error">${escapeText(operation.error)}</small>` : ""}</div></div>`;
    }).join("")}</div>
  </section>`;
}

function renderGraph(graph) {
  const container = $("#graph");
  if (!graph?.nodes?.length) { container.innerHTML = ""; return; }
  const columnFor = (node) => {
    if (node.id === "parent") return 0;
    if (node.id === "inquiry") return 1;
    if (node.id === "packet") return 2;
    if (["embodied", "cybernetic", "infinite"].includes(node.id)) return 3;
    if (node.id === "folding") return 4;
    if (node.kind === "option") return 5;
    if (node.id === "decision") return 6;
    if (node.id === "experiment") return 7;
    if (node.id === "outcome") return 8;
    if (node.id === "artifact") return 9;
    return 6;
  };
  const grouped = {};
  graph.nodes.forEach((node) => { const key = columnFor(node); (grouped[key] ||= []).push(node); });
  const positions = {};
  Object.entries(grouped).forEach(([column, nodes]) => {
    nodes.forEach((node, index) => { positions[node.id] = { x: 35 + Number(column) * 150, y: 45 + index * 105 }; });
  });
  const width = Math.max(760, 100 + Math.max(...Object.values(positions).map((p) => p.x)) + 140);
  const height = Math.max(390, 90 + Math.max(...Object.values(positions).map((p) => p.y)));
  const edgeMarkup = graph.edges.map((edge) => {
    const a = positions[edge.source], b = positions[edge.target];
    if (!a || !b) return "";
    const actual = !edge.optional ? " actual" : " optional";
    return `<path class="edge${actual}" d="M ${a.x + 120} ${a.y + 31} C ${a.x + 137} ${a.y + 31}, ${b.x - 17} ${b.y + 31}, ${b.x} ${b.y + 31}"/>`;
  }).join("");
  const labelLines = (label) => {
    const words = String(label).split(/\s+/);
    const lines = [""];
    words.forEach((word) => {
      const current = lines[lines.length - 1];
      if (current && `${current} ${word}`.length > 18 && lines.length < 2) lines.push(word);
      else lines[lines.length - 1] = current ? `${current} ${word}` : word;
    });
    return lines.map((line) => line.slice(0, 22));
  };
  const nodeMarkup = graph.nodes.map((node) => {
    const p = positions[node.id];
    const lines = labelLines(node.label);
    return `<g class="node ${escapeText(node.status)} ${node.optional ? "optional" : ""} ${node.kind === "human" ? "human" : ""}" data-node="${escapeText(node.id)}" transform="translate(${p.x},${p.y})"><rect width="120" height="62"></rect><text class="kind" x="9" y="16">${escapeText(node.kind.toUpperCase())}</text><text x="9" y="37">${escapeText(lines[0] || "")}</text><text x="9" y="52">${escapeText(lines[1] || "")}</text></g>`;
  }).join("");
  const arrows = edgeMarkup.replaceAll('/>', ' marker-end="url(#round-arrow)"/>');
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="min-width:${width}px" aria-hidden="true"><defs><marker id="round-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 8 4 L 0 8 z"></path></marker></defs>${arrows}${nodeMarkup}</svg>`;
  container.querySelectorAll("[data-node]").forEach((element) => element.addEventListener("click", () => {
    const node = graph.nodes.find((item) => item.id === element.dataset.node);
    $("#node-detail").innerHTML = `<strong>${escapeText(node.label)}</strong> · ${escapeText(statusLabel(node.status))}<br>${escapeText(node.detail || "No additional detail recorded for this node.")}`;
  }));
}

async function submitRound(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    title: form.get("title"), inquiry: form.get("inquiry"),
    feedback_project_id: form.get("feedback_project_id"), folding_project_id: form.get("folding_project_id"),
    motif_ids: form.getAll("motif_ids"), checkpoint_ids: form.getAll("checkpoint_ids"), human_note: form.get("human_note"),
  };
  try { const round = await api("/api/rounds", { method: "POST", body: payload }); await openRound(round.id); }
  catch (error) { notify(error.message); }
}

async function submitSelection(event) {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const payload = { fold_id: form.get("fold_id"), aim: form.get("aim"), scope: form.get("scope"), stop_condition: form.get("stop_condition"), protected_boundary: form.get("protected_boundary"), participants: form.getAll("participants") };
  try { state.current = await api(`/api/rounds/${state.current.id}/selection`, { method: "POST", body: payload }); renderCurrent(); }
  catch (error) { notify(error.message); }
}

async function enactRound() {
  try { state.current = await api(`/api/rounds/${state.current.id}/enact`, { method: "POST" }); renderCurrent(); managePolling(); }
  catch (error) { notify(error.message); }
}

async function submitCloseout(event) {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  try { state.current = await api(`/api/rounds/${state.current.id}/close`, { method: "POST", body: payload }); renderCurrent(); await refreshRoundList(); }
  catch (error) { notify(error.message); }
}

async function submitRefold(event) {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try { const child = await api(`/api/rounds/${state.current.id}/refold`, { method: "POST", body: Object.fromEntries(form.entries()) }); await openRound(child.id); }
  catch (error) { notify(error.message); }
}

async function retryCycle() {
  const button = $("#retry-cycle");
  button.disabled = true;
  button.textContent = "RE-RUNNING…";
  try {
    state.current = await api(`/api/rounds/${state.current.id}/retry`, { method: "POST" });
    renderCurrent();
    await refreshRoundList();
  } catch (error) {
    button.disabled = false;
    button.textContent = "RE-RUN CYCLE";
    notify(error.message);
  }
}

function managePolling() {
  if (state.polling) window.clearInterval(state.polling);
  if (!state.current || !["running", "queued"].includes(state.current.status)) return;
  state.polling = window.setInterval(async () => {
    try {
      const updated = await api(`/api/rounds/${state.current.id}`);
      const roundChanged = updated.updated_at !== state.current.updated_at;
      const progressChanged = JSON.stringify(updated.folding_progress || null) !== JSON.stringify(state.current.folding_progress || null);
      if (roundChanged || progressChanged) {
        state.current = updated;
        renderCurrent();
        if (roundChanged) await refreshRoundList();
      }
      if (!["running", "queued"].includes(updated.status)) { window.clearInterval(state.polling); state.polling = null; }
    } catch (error) { notify(error.message); }
  }, 1800);
}

$("#round-form").addEventListener("submit", submitRound);
$("#feedback-project").addEventListener("change", (event) => loadMotifs(event.target.value));
$("#new-round").addEventListener("click", () => {
  state.current = null; if (state.polling) window.clearInterval(state.polling);
  $("#round-form").classList.remove("hidden"); $("#active-step").classList.add("hidden");
  $("#map-title").textContent = "New round"; $("#graph").innerHTML = ""; $("#analysis").innerHTML = ""; $("#map-actions").innerHTML = "";
  renderRoundList(state.session.rounds || []);
});

initialize().catch((error) => notify(error.message));
