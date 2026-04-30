const ui = {
  chainLen: document.getElementById("chainLen"),
  pendingCount: document.getElementById("pendingCount"),
  consensus: document.getElementById("consensus"),
  budgets: document.getElementById("agentBudgets"),
  events: document.getElementById("events"),
  actionMsg: document.getElementById("actionMsg"),
};

async function callAction(payload) {
  const res = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

function money(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

function renderBudgets(agents) {
  ui.budgets.innerHTML = "";
  agents.forEach((a) => {
    const item = document.createElement("article");
    item.className = "budget-item";
    const spent = a.spent_confirmed + a.spent_pending;
    const left = Math.max(a.limit - spent, 0);

    item.innerHTML = `
      <div class="budget-row">
        <strong>Agent ${a.agent}</strong>
        <code>Limit ${money(a.limit)}</code>
      </div>
      <div class="budget-row">
        <span>Spent ${money(spent)}</span>
        <span>Left ${money(left)}</span>
      </div>
    `;
    ui.budgets.appendChild(item);
  });
}

function renderEvents(events) {
  ui.events.innerHTML = "";
  [...events]
    .reverse()
    .slice(0, 40)
    .forEach((e) => {
      const row = document.createElement("div");
      row.className = "event";
      const t = new Date(e.ts * 1000).toLocaleTimeString();
      row.textContent = `[${t}] ${e.text}`;
      ui.events.appendChild(row);
    });
}

function setActionMessage(msg, ok = true) {
  ui.actionMsg.textContent = msg;
  ui.actionMsg.style.color = ok ? "#1f8d56" : "#c4382b";
}

async function refreshState() {
  const res = await fetch("/api/state");
  const state = await res.json();
  if (!state.ready) {
    ui.chainLen.textContent = "-";
    ui.pendingCount.textContent = "-";
    ui.consensus.textContent = "offline";
    ui.consensus.className = "consensus-bad";
    return;
  }

  ui.chainLen.textContent = state.chain_length;
  ui.pendingCount.textContent = state.pending_count;
  ui.consensus.textContent = state.consensus ? "YES" : "NO";
  ui.consensus.className = state.consensus ? "consensus-ok" : "consensus-bad";

  renderBudgets(state.agents || []);
  renderEvents(state.events || []);
}

async function bindActions() {
  document.getElementById("resetBtn").onclick = async () => {
    const r = await callAction({ action: "reset" });
    setActionMessage(r.msg, r.ok);
    await refreshState();
  };

  document.getElementById("demoBtn").onclick = async () => {
    setActionMessage("Running business demo sequence...", true);
    const r = await callAction({ action: "run_demo" });
    setActionMessage(r.msg, r.ok);
    await refreshState();
  };

  document.getElementById("mineBtn").onclick = async () => {
    const r = await callAction({ action: "mine", node: 1 });
    setActionMessage(r.msg, r.ok);
    await refreshState();
  };
}

(async function init() {
  await bindActions();
  await refreshState();
  setInterval(refreshState, 2000);
})();
