"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (n == null ? "" : "₹" + Number(n).toLocaleString("en-IN"));
const KINDS = ["invoice", "bill", "receipt", "warranty", "insurance", "id_proof", "other"];
const KIND_LABEL = { invoice: "Invoice", bill: "Bill", receipt: "Receipt", warranty: "Warranty", insurance: "Insurance", id_proof: "ID proof", other: "Other" };
const STATUS_LABEL = { awaiting_approval: "Needs your approval", sent: "Sent", resolved: "Resolved" };

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : res.statusText);
  return body;
}
const postJSON = (path, data, method = "POST") =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

async function busy(btn, fn) {
  const label = btn.textContent; btn.disabled = true; btn.textContent = "Working…";
  try { await fn(); } catch (e) { toast(e.message); } finally { btn.disabled = false; btn.textContent = label; }
}

// ---------- navigation ----------
const LOADERS = { due: loadDue, vault: loadVault, cases: loadCases, add: () => {} };
function show(tab) {
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + tab));
  document.querySelectorAll("nav.bottom button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  if (LOADERS[tab]) LOADERS[tab]().catch((e) => toast(e.message));
  if (location.hash !== "#" + tab && tab !== "detail") history.replaceState(null, "", "#" + tab);
  window.scrollTo(0, 0);
}
document.querySelectorAll("nav.bottom button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
document.addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) show(g.dataset.go); });

// ---------- today ----------
async function loadDue() {
  const items = await api("/due?days=30");
  const el = $("#due-list");
  if (!items.length) { el.innerHTML = `<div class="empty">Nothing due in the next 30 days. Add documents to start tracking.</div>`; return; }
  el.innerHTML = items.map((i) => `
    <div class="card">
      <div class="row"><h2>${esc(i.title)}</h2><span class="badge ${i.urgency}">${esc(i.urgency)}</span></div>
      <div class="meta">${esc(i.detail)}</div>
      <div class="actions">
        ${i.document_id ? `<button data-open-doc="${i.document_id}">View</button>` : ""}
        ${i.type === "expiry" && ["invoice", "warranty"].includes(i.kind) ? `<button class="dark" data-report="${i.document_id}">Report a problem</button>` : ""}
        ${i.type === "anomaly" ? `<button class="dark" data-dispute="${i.document_id}">Dispute this bill</button>` : ""}
        ${i.case_id ? `<button class="dark" data-go="cases">Open case</button>` : ""}
      </div>
    </div>`).join("");
}

document.addEventListener("click", async (e) => {
  const open = e.target.closest("[data-open-doc]");
  if (open) return openDetail(open.dataset.openDoc);
  const report = e.target.closest("[data-report]");
  if (report) {
    const issue = prompt("What's wrong? (e.g. The AC stopped cooling)");
    if (issue) busy(report, async () => { await postJSON("/cases", { issue, document_id: Number(report.dataset.report) }); toast("Draft ready for your approval"); show("cases"); });
  }
  const dispute = e.target.closest("[data-dispute]");
  if (dispute) {
    const issue = prompt("Describe the problem with this bill", "This bill is much higher than my usual usage. Please check the meter reading and correct the bill.");
    if (issue) busy(dispute, async () => { await postJSON("/cases", { issue, document_id: Number(dispute.dataset.dispute) }); toast("Draft ready for your approval"); show("cases"); });
  }
});

// ---------- add ----------
$("#add-file").addEventListener("change", (e) => {
  const f = e.target.files[0];
  $("#add-file-label").textContent = f ? `📎 ${f.name}` : "Take a photo or choose a file";
});

$("#add-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.target; const btn = form.querySelector("button[type=submit]");
  const data = new FormData(form);
  if (!$("#add-file").files.length) data.delete("file");
  busy(btn, async () => {
    const res = await api("/documents/ingest", { method: "POST", body: data });
    form.reset(); $("#add-file-label").textContent = "Take a photo or choose a file";
    renderReview(res);
  });
});

function field(name, label, value, type = "text") {
  return `<label>${label}<input name="${name}" type="${type}" value="${esc(value ?? "")}" ${type === "number" ? 'step="any"' : ""}></label>`;
}

function renderReview(res) {
  const d = res.document;
  $("#add-result").innerHTML = `
    <form id="review-form" class="card" data-id="${d.id}">
      <div class="row"><h2>Filed: ${esc(d.title)}</h2><span class="badge ${res.used_ai ? "low" : "medium"}">${res.used_ai ? "Read by Claude" : "Check details"}</span></div>
      ${res.warning ? `<div class="flag">${esc(res.warning)}</div>` : ""}
      ${d.anomaly ? `<div class="flag">⚠ ${esc(d.anomaly.message)}</div>` : ""}
      <div class="grid2">
        <label>Type<select name="kind">${KINDS.map((k) => `<option value="${k}" ${k === d.kind ? "selected" : ""}>${KIND_LABEL[k]}</option>`).join("")}</select></label>
        ${field("title", "Title", d.title)}
        ${field("vendor", "Vendor / issuer", d.vendor)}
        ${field("item_name", "Item", d.item_name)}
        ${field("category", "Bill category", d.category)}
        ${field("amount", "Amount (₹)", d.amount, "number")}
        ${field("doc_date", "Date", d.doc_date, "date")}
        ${field("warranty_months", "Warranty (months)", d.warranty_months, "number")}
        ${field("expiry_date", "Expiry / due date", d.expiry_date, "date")}
        ${field("contact_email", "Support email", d.contact_email, "email")}
      </div>
      <div class="actions"><button class="primary" type="submit">Save</button><button type="button" data-open-doc="${d.id}">View timeline</button></div>
    </form>`;
  $("#review-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const f = e.target; const body = {};
    new FormData(f).forEach((v, k) => { body[k] = v === "" ? null : v; });
    for (const k of ["amount", "warranty_months"]) if (body[k] != null) body[k] = Number(body[k]);
    if (!body.expiry_date) delete body.expiry_date;
    busy(f.querySelector("button[type=submit]"), async () => {
      const saved = await postJSON(`/documents/${f.dataset.id}`, body, "PATCH");
      renderReview({ document: saved, used_ai: true, warning: null });
      toast("Saved");
    });
  });
}

// ---------- vault ----------
let searchTimer;
$("#vault-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadVault().catch((e) => toast(e.message)), 250); });

async function loadVault() {
  const q = $("#vault-search").value.trim();
  const docs = await api("/documents" + (q ? `?q=${encodeURIComponent(q)}` : ""));
  const el = $("#vault-list");
  if (!docs.length) { el.innerHTML = `<div class="empty">${q ? "No matches." : "No documents yet. Use Add to file your first one."}</div>`; return; }
  el.innerHTML = docs.map((d) => `
    <div class="card clickable" data-open-doc="${d.id}">
      <div class="row"><h2>${esc(d.title)}</h2><span class="badge neutral">${KIND_LABEL[d.kind] || d.kind}</span></div>
      <div class="meta">${[d.vendor, money(d.amount), d.doc_date, d.expiry_date ? "expires/due " + d.expiry_date : ""].filter(Boolean).map(esc).join(" · ")}</div>
      ${d.needs_review ? `<div class="flag">Details need checking</div>` : ""}
    </div>`).join("");
}

async function openDetail(id) {
  const t = await api(`/documents/${id}/timeline`);
  const d = t.document;
  $("#detail").innerHTML = `
    <div class="card">
      <div class="row"><h1>${esc(d.title)}</h1><span class="badge neutral">${KIND_LABEL[d.kind] || d.kind}</span></div>
      <div class="meta">${[d.vendor, d.item_name, money(d.amount), d.doc_date].filter(Boolean).map(esc).join(" · ")}</div>
      ${t.warranty ? `<div class="flag">${esc(t.warranty)}</div>` : ""}
      ${d.anomaly ? `<div class="flag">⚠ ${esc(d.anomaly.message)}</div>` : ""}
      ${d.notes ? `<p>${esc(d.notes)}</p>` : ""}
      <div class="actions">
        ${d.file_name ? `<a href="/api/documents/${d.id}/file" target="_blank"><button>Open file</button></a>` : ""}
        <button class="dark" data-report="${d.id}">Report a problem</button>
        <button data-edit="${d.id}">Edit details</button>
      </div>
      <h2>Timeline</h2>
      <ul class="events">${t.events.map((e) => `<li><time>${esc(String(e.at).slice(0, 10))}</time>${esc(e.kind.replace(/_/g, " "))}${e.note ? " – " + esc(e.note) : ""}</li>`).join("")}</ul>
    </div>`;
  $("#detail [data-edit]").addEventListener("click", () => { show("add"); renderReview({ document: d, used_ai: !d.needs_review, warning: null }); });
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-detail"));
  window.scrollTo(0, 0);
}

// ---------- cases ----------
async function loadCases() {
  const cases = await api("/cases");
  const el = $("#cases-list");
  if (!cases.length) { el.innerHTML = `<div class="empty">No complaints yet. Use “Report a problem” on a document.</div>`; return; }
  el.innerHTML = cases.map((c) => {
    const badge = c.status === "awaiting_approval" ? "high" : c.status === "sent" ? "medium" : "low";
    const overdue = c.status === "sent" && c.follow_up_on && c.follow_up_on <= new Date().toISOString().slice(0, 10);
    return `
    <div class="card" data-case="${c.id}">
      <div class="row"><h2>${esc(c.issue)}</h2><span class="badge ${badge}">${STATUS_LABEL[c.status]}</span></div>
      ${c.escalation_level ? `<div class="meta">Escalation level ${c.escalation_level}</div>` : ""}
      ${c.status === "awaiting_approval" ? `
        <label>To<input name="to_email" type="email" value="${esc(c.to_email)}" placeholder="support@company.com"></label>
        <label>Subject<input name="subject" value="${esc(c.subject)}"></label>
        <label>Email<textarea name="body" rows="9">${esc(c.body)}</textarea></label>
        <div class="actions"><button class="primary" data-approve="${c.id}">Approve &amp; send</button></div>` : `
        <div class="meta">${esc(c.subject)}</div>
        ${c.status === "sent" ? `<div class="${overdue ? "flag" : "meta"}">${overdue ? "No reply yet. Escalate?" : "Follow up on " + esc(c.follow_up_on)}</div>
        <div class="actions"><a href="${esc(c.mailto)}"><button>Open email again</button></a><button class="dark" data-escalate="${c.id}">Escalate</button><button data-resolve="${c.id}">Mark resolved</button></div>` : ""}`}
      <ul class="events">${c.events.map((e) => `<li><time>${esc(e.at.slice(0, 10))}</time>${esc(e.kind.replace(/_/g, " "))}${e.note ? " – " + esc(e.note) : ""}</li>`).join("")}</ul>
    </div>`;
  }).join("");
}

$("#cases-list").addEventListener("click", (e) => {
  const approve = e.target.closest("[data-approve]");
  if (approve) {
    const card = approve.closest("[data-case]");
    const body = { to_email: $("[name=to_email]", card).value || null, subject: $("[name=subject]", card).value, body: $("[name=body]", card).value };
    if (!confirm("Approve this email? Your mail app will open with it ready to send.")) return;
    return busy(approve, async () => {
      const c = await postJSON(`/cases/${approve.dataset.approve}/approve`, body);
      window.location.href = c.mailto;
      toast("Approved. Follow-up reminder set for " + c.follow_up_on);
      loadCases();
    });
  }
  const esc_ = e.target.closest("[data-escalate]");
  if (esc_) return busy(esc_, async () => { await postJSON(`/cases/${esc_.dataset.escalate}/escalate`, {}); toast("Escalation drafted"); loadCases(); });
  const res = e.target.closest("[data-resolve]");
  if (res) return busy(res, async () => { await postJSON(`/cases/${res.dataset.resolve}/resolve`, {}); toast("Marked resolved"); loadCases(); });
});

// ---------- start ----------
api("/status").then((s) => { $("#ai-status").textContent = s.ai ? "AI reading on" : "AI reading off"; }).catch(() => {});
show((location.hash || "#due").slice(1) in LOADERS ? (location.hash || "#due").slice(1) : "due");
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
