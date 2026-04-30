let appState = null;
let refreshing = false;
let lastRefreshMs = 0;

const MIN_REFRESH_MS = 250;
const POLL_MS = 3000;

function el(id) {
  return document.getElementById(id);
}

function money(n) {
  return `$${Number(n || 0).toFixed(2)}`;
}

function periodLabel(days) {
  if (days === 1) return "Daily";
  if (days === 7) return "Weekly";
  if (days === 30) return "Monthly";
  return `${days}d`;
}

async function apiAction(action, payload = {}) {
  const res = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...payload }),
  });
  return res.json();
}

function setLoading(buttonId, isLoading, defaultLabel) {
  const btn = el(buttonId);
  if (!btn) return;
  btn.disabled = isLoading;
  btn.textContent = isLoading ? "Working..." : defaultLabel;
}

function readPeriodDays() {
  const select = el("periodSelect").value;
  if (select === "custom") {
    const d = parseInt(el("periodCustom").value, 10);
    return Number.isFinite(d) && d > 0 ? d : null;
  }
  const d = parseInt(select, 10);
  return Number.isFinite(d) && d > 0 ? d : null;
}

async function setBudget() {
  const amount = parseFloat(el("budgetInput").value);
  const periodDays = readPeriodDays();
  if (!Number.isFinite(amount) || amount <= 0 || !periodDays) {
    alert("Enter a valid budget and period.");
    return;
  }

  setLoading("setBudgetBtn", true, "Set Budget");
  try {
    const out = await apiAction("set_budget", {
      amount,
      period_days: periodDays,
    });
    if (!out.ok) alert(out.msg || out.error || "Failed to set budget.");
    await refreshState(true);
  } finally {
    setLoading("setBudgetBtn", false, "Set Budget");
  }
}

async function searchProducts() {
  const budget = parseFloat(el("budgetInput").value);
  const style = el("styleSelect").value;
  const size = (el("sizeInput").value || "M").trim();
  const occasion = (el("occasionInput").value || "").trim() || null;

  if (!Number.isFinite(budget) || budget <= 0) {
    alert("Set a valid budget first.");
    return;
  }

  setLoading("searchBtn", true, "Find Items");
  try {
    const out = await apiAction("search", { budget, style, size, occasion });
    if (!out.ok) alert(out.msg || out.error || "Search failed.");
    await refreshState(true);
  } finally {
    setLoading("searchBtn", false, "Find Items");
  }
}

async function approveProduct(idx) {
  const out = await apiAction("approve", { product_idx: idx });
  if (!out.ok) alert(out.msg || out.error || "Approval failed.");
  await refreshState(true);
}

async function rejectProduct(idx) {
  const out = await apiAction("reject", { product_idx: idx });
  if (!out.ok) alert(out.msg || out.error || "Reject failed.");
  await refreshState(true);
}

async function mineBlock() {
  setLoading("mineBtn", true, "Mine Block");
  try {
    await apiAction("mine");
    await refreshState(true);
  } finally {
    setLoading("mineBtn", false, "Mine Block");
  }
}

async function resetNetwork() {
  if (!confirm("Reset the network and clear all state?")) return;
  setLoading("resetBtn", true, "Reset");
  try {
    await apiAction("reset");
    await refreshState(true);
  } finally {
    setLoading("resetBtn", false, "Reset");
  }
}

function renderFindings() {
  const section = el("findingsSection");
  const list = el("findingsList");
  const items = appState?.pending_findings || [];

  if (!items.length) {
    section.style.display = "none";
    list.innerHTML = "";
    return;
  }

  section.style.display = "block";
  list.innerHTML = items
    .map((p, idx) => {
      const url = p.link?.startsWith("http") ? p.link : `https://${p.link}`;
      return `
        <article class="finding-card">
          <div class="finding-header">
            <h3>${p.name}</h3>
            <span class="badge">${p.brand}</span>
          </div>
          <div class="finding-meta">
            <div><span>Price</span><strong>${money(p.price)}</strong></div>
            <div><span>Size</span><strong>${p.size}</strong></div>
            <div><span>Site</span><a href="${url}" target="_blank" rel="noopener noreferrer">Open listing</a></div>
          </div>
          <div class="finding-actions">
            <button class="btn btn-primary" onclick="approveProduct(${idx})">Approve</button>
            <button class="btn btn-secondary" onclick="rejectProduct(${idx})">Reject</button>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderApproved() {
  const list = el("approvedList");
  const items = appState?.approved_items || [];
  if (!items.length) {
    list.innerHTML = '<p class="empty-state">Nothing approved yet.</p>';
    return;
  }
  list.innerHTML = items
    .map(
      (p) =>
        `<div class="approved-item"><strong>${p.name}</strong><span>${p.brand}</span><span>${money(p.price)}</span></div>`,
    )
    .join("");
}

function renderBudgetAndStatus() {
  const s = appState?.shopper || {
    budget: 0,
    total: 0,
    remaining: 0,
    utilization: 0,
  };

  el("budgetLimit").textContent = money(s.budget);
  el("budgetSpent").textContent = money(s.total);
  el("budgetRemaining").textContent = money(s.remaining);

  const periodDays = readPeriodDays() || 7;
  el("periodDisplay").textContent = periodLabel(periodDays);

  const pct = Math.max(0, Math.round((s.utilization || 0) * 100));
  el("progressFill").style.width = `${Math.min(pct, 100)}%`;
  el("progressText").textContent = `${pct}% used`;

  el("chainHeight").textContent = String(appState?.chain_length ?? "-");
  el("pendingCount").textContent = String(appState?.pending_count ?? "-");
  el("consensus").textContent = appState?.consensus ? "YES" : "NO";
}

function renderActivity() {
  const list = el("activityList");
  const events = appState?.events || [];
  if (!events.length) {
    list.innerHTML = '<p class="empty-state">No activity yet.</p>';
    return;
  }

  list.innerHTML = events
    .slice(-60)
    .reverse()
    .map((ev) => {
      const t = new Date(ev.ts * 1000).toLocaleTimeString();
      return `<div class="activity-item"><span>${ev.text}</span><small>${t}</small></div>`;
    })
    .join("");
}

function render() {
  renderBudgetAndStatus();
  renderFindings();
  renderApproved();
  renderActivity();
}

async function refreshState(force = false) {
  const now = Date.now();
  if (!force && (refreshing || now - lastRefreshMs < MIN_REFRESH_MS)) return;

  refreshing = true;
  try {
    const res = await fetch("/api/state");
    appState = await res.json();
    render();
    lastRefreshMs = Date.now();
  } catch (err) {
    console.error("refresh failed", err);
  } finally {
    refreshing = false;
  }
}

function setupPeriodUI() {
  const select = el("periodSelect");
  const custom = el("periodCustom");
  select.addEventListener("change", () => {
    custom.style.display = select.value === "custom" ? "block" : "none";
    if (select.value !== "custom") custom.value = "";
    renderBudgetAndStatus();
  });
}

window.setBudget = setBudget;
window.searchProducts = searchProducts;
window.approveProduct = approveProduct;
window.rejectProduct = rejectProduct;
window.mineBlock = mineBlock;
window.resetNetwork = resetNetwork;

document.addEventListener("DOMContentLoaded", async () => {
  setupPeriodUI();
  await refreshState(true);
  setInterval(() => refreshState(false), POLL_MS);
});
