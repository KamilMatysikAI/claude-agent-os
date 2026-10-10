// Agent panel front end. Vanilla JS, no build step, no network beyond this server.
// Screens: Today, Decisions (stack), Projects (+ tree, project page), Activity, All tasks.
// Every write goes through /api/actions. Closing actions return a pending id and are
// applied by the server after 5 s, so "Undo" is real, not cosmetic.

const UNDO_MS = 5000;
const ARM_MS = 3000;
const REFRESH_MS = 60000;
const LS = { theme: "agentos.theme", visit: "agentos.lastVisit", seen: "agentos.thisVisit" };

const S = {
  meta: null, today: null, decisions: null, projects: null, tree: null, project: null,
  activity: null, tasks: null, route: { view: "today", rest: "", q: {} },
  decIdx: 0, armed: null, lastUndo: null, lastOk: null, offline: false, sel: -1,
  drawer: null, editing: false, closingAsk: false, lastVisit: null, gAt: 0,
};

// ── helpers ─────────────────────────────────────────────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name, cls = "") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const LONG_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function parseDay(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}
function fmtDay(iso, long = false) {
  const d = parseDay(iso);
  if (!d) return "";
  return `${(long ? LONG_DAYS : DAYS)[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}
function fmtStamp(iso) {
  if (!iso) return "";
  const time = iso.length > 10 ? iso.slice(11, 16) : "";
  const day = iso.slice(0, 10);
  const today = S.meta?.today;
  if (day === today) return time ? `today ${time}` : "today";
  return `${fmtDay(day)}${time ? " " + time : ""}`;
}
function localIso(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function dueInfo(s) {
  // a closed task shows when it closed; its old due date ("tomorrow") would mislead
  if (s.closed && (s.status === "done" || s.status === "cancelled")) return { text: `${s.status === "cancelled" ? "cancelled" : "closed"} ${fmtDay(s.closed)}`, cls: "" };
  if (!s.due) return { text: "", cls: "" };
  if (s.overdue_days > 0) return { text: s.overdue_days === 1 ? "1 day overdue" : `${s.overdue_days} days overdue`, cls: "over" };
  const today = parseDay(S.meta?.today || localIso());
  const diff = Math.round((parseDay(s.due) - today) / 86400000);
  if (diff === 0) return { text: "today", cls: "today" };
  if (diff === 1) return { text: "tomorrow", cls: "" };
  return { text: fmtDay(s.due), cls: "" };
}
const ROLE = { ceo: "CEO", soft: "software", web: "web", copy: "copy", marketing: "marketing", research: "research", human: "you", you: "you" };
const who = (s) => (s.human ? "you" : ROLE[s.owner] || s.owner || "agent");

// tiny, safe markdown: escape first, then a small subset
function md(text) {
  if (!text) return "";
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, href) => {
      const raw = href.replace(/&amp;/g, "&");
      return /^https?:\/\//i.test(raw)
        ? `<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : `${label} <code>${href}</code>`;
    });
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of text.replace(/\r/g, "").split("\n")) {
    const t = line.trim();
    let m;
    if (!t) { close(); continue; }
    if ((m = t.match(/^#{1,6}\s+(.*)$/))) { close(); out.push(`<h3>${inline(m[1])}</h3>`); continue; }
    if ((m = t.match(/^[-*]\s+\[([ xX])\]\s+(.*)$/))) {
      if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; }
      out.push(`<li class="task${m[1] === " " ? "" : " done"}">${inline(m[2])}</li>`); continue;
    }
    if ((m = t.match(/^[-*]\s+(.*)$/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if ((m = t.match(/^\d+[.)]\s+(.*)$/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    close();
    out.push(`<p>${inline(t)}</p>`);
  }
  close();
  return `<div class="md">${out.join("")}</div>`;
}

// drop a leading "# Title" that repeats the task title, and headings with no content
function cleanBody(body, title) {
  const lines = (body || "").replace(/\r/g, "").split("\n");
  const first = lines.findIndex((l) => l.trim());
  if (first >= 0) {
    const h = lines[first].match(/^#\s+(.+)$/);
    if (h && h[1].trim().toLowerCase() === String(title).trim().toLowerCase()) lines.splice(first, 1);
  }
  // drop "## Heading" blocks that have nothing under them
  const out = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (/^##\s/.test(lines[i])) {
      let j = i + 1;
      while (j < lines.length && !lines[j].trim()) j += 1;
      if (j >= lines.length || /^##\s/.test(lines[j])) { i = j - 1; continue; }
    }
    out.push(lines[i]);
  }
  return out.join("\n");
}

// ── network ─────────────────────────────────────────────────────────────────
async function api(path) {
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" }, cache: "no-store" });
    const data = await res.json().catch(() => ({}));
    setOffline(false);
    if (!res.ok) throw Object.assign(new Error(data.error || `HTTP ${res.status}`), { status: res.status });
    return data;
  } catch (err) {
    if (err.status) throw err;
    setOffline(true);
    throw err;
  }
}
async function post(path, body) {
  let res;
  try {
    res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (err) {
    setOffline(true);
    throw new Error("No connection to the panel. Nothing was saved.");
  }
  setOffline(false);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(data.error || `The panel answered ${res.status}.`);
  return data;
}
function setOffline(off) {
  const bar = $("#offline");
  if (!off) {
    S.lastOk = new Date();
    if (S.offline) { S.offline = false; bar.hidden = true; document.body.classList.remove("is-offline"); }
    return;
  }
  if (!S.offline) S.offlineSince = new Date();
  S.offline = true;
  const t = (d) => (d ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : "—");
  bar.textContent = `No connection to the panel since ${t(S.offlineSince)}. Showing data from ${t(S.lastOk)}. Actions are paused until it is back.`;
  bar.hidden = false;
  document.body.classList.add("is-offline");
}

// ── toasts and undo ─────────────────────────────────────────────────────────
function toast(msg, { error = false, action = null, actionLabel = "", ms = 5000, timer = false } = {}) {
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast" + (error ? " err" : "");
  el.setAttribute("role", error ? "alert" : "status");
  el.innerHTML = `<span class="msg">${esc(msg)}</span>${timer ? `<span class="tmr">${Math.round(ms / 1000)} s</span>` : ""}${action ? `<button type="button">${esc(actionLabel)}</button>` : ""}`;
  box.appendChild(el);
  let left = ms;
  const tick = timer ? setInterval(() => { left -= 1000; const t = $(".tmr", el); if (t) t.textContent = `${Math.max(0, Math.round(left / 1000))} s`; }, 1000) : null;
  const done = () => { clearInterval(tick); el.remove(); };
  if (action) $("button", el).addEventListener("click", () => { done(); action(); });
  setTimeout(done, ms);
  return done;
}

// run a closing action (done / cancel / decide) with the server-side undo window
async function closing(body, { label, restore, after }) {
  let res;
  try {
    res = await post("/api/actions", body);
  } catch (err) {
    restore?.();
    toast(`Not saved: ${err.message}`, { error: true, action: () => closing(body, { label, restore, after }), actionLabel: "Retry", ms: 9000 });
    return;
  }
  const id = res.pending.id;
  const undo = async () => {
    S.lastUndo = null;
    try {
      await post("/api/undo", { id });
      restore?.();
      toast(`Undone: ${label.toLowerCase()}.`);
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
  S.lastUndo = { id, undo, until: Date.now() + UNDO_MS };
  const dismiss = toast(label, { action: undo, actionLabel: "Undo", ms: UNDO_MS, timer: true });
  setTimeout(async () => {
    if (S.lastUndo?.id === id) S.lastUndo = null;
    dismiss();
    try {
      let st = await api(`/api/pending/${id}`);
      for (let i = 0; i < 6 && (st.status === "pending" || st.status === "applying"); i += 1) {
        await new Promise((r) => setTimeout(r, 500));
        st = await api(`/api/pending/${id}`);
      }
      if (st.status === "failed") {
        restore?.();
        toast(`Not saved: ${st.error}`, { error: true, action: () => closing(body, { label, restore, after }), actionLabel: "Retry", ms: 10000 });
      }
    } catch (_) { /* offline bar already explains it */ }
    after?.();
    refreshCounts();
  }, UNDO_MS + 400);
}

// ── routing ─────────────────────────────────────────────────────────────────
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "") || "today";
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/");
  const q = Object.fromEntries(new URLSearchParams(query));
  return { view: parts[0] || "today", rest: decodeURIComponent(parts.slice(1).join("/")), q };
}
function hashFor(view, rest = "", q = {}) {
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v)).toString();
  return `#/${view}${rest ? "/" + rest : ""}${qs ? "?" + qs : ""}`;
}
function taskHref(key) {
  const r = S.route;
  return hashFor(r.view, r.rest, { ...r.q, task: key });
}
function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }

const VIEWS = {
  today: { title: "Today", nav: "today", render: renderToday },
  decisions: { title: "Decisions", nav: "decisions", render: renderDecisions },
  projects: { title: "Projects", nav: "projects", render: renderProjects },
  tree: { title: "Projects", nav: "projects", render: renderTree },
  activity: { title: "Activity", nav: "activity", render: renderActivity },
  tasks: { title: "All tasks", nav: "tasks", render: renderTasks },
};

async function route() {
  const prev = S.route;
  S.route = parseHash();
  const v = VIEWS[S.route.view] ? S.route.view : "today";
  const def = VIEWS[v];
  const sameView = prev.view === S.route.view && prev.rest === S.route.rest
    && JSON.stringify({ ...prev.q, task: "" }) === JSON.stringify({ ...S.route.q, task: "" });
  $$("[data-view]").forEach((a) => (a.dataset.view === def.nav ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  $("#view-title").textContent = def.title;
  [...document.body.classList].filter((c) => c.startsWith("v-")).forEach((c) => document.body.classList.remove(c));
  document.body.classList.add(`v-${v}`);
  $("#view-sub").textContent = v === "today" && S.meta ? fmtDay(S.meta.today, true) : "";
  if (!sameView || !$("#main").dataset.ready) {
    S.sel = -1;
    await def.render();
    $("#main").dataset.ready = "1";
    if (v === "activity" || v === "today") markVisit();
  }
  if (S.route.q.task) openDrawer(S.route.q.task); else closeDrawer(false);
}
function main(html) {
  $("#main").innerHTML = html;
  // bar widths via CSSOM: the CSP forbids inline style attributes
  $$("[data-w]", $("#main")).forEach((el) => { el.style.width = `${Math.max(0, Math.min(100, Number(el.dataset.w) || 0))}%`; });
}
function errorBox(err, retry) {
  main(`<div class="sec"><div class="sec-empty">Could not load this screen: ${esc(err.message)}. ${retry ? '<button class="link-btn" data-act="reload">Try again</button>' : ""}</div></div>`);
}

// ── rows ────────────────────────────────────────────────────────────────────
function chips(s) {
  const out = [];
  if (s.working) out.push(`<span class="chip agent keep"><span class="pulse"></span>working</span>`);
  if (s.status === "blocked") out.push(`<span class="chip stop keep">${icon("block")}blocked</span>`);
  if (s.unblocks > 0) out.push(`<span class="chip agent" title="Agent tasks waiting on this">unblocks ${s.unblocks}</span>`);
  if (s.type === "review") out.push(`<span class="chip">review</span>`);
  if (s.priority === "high" && s.status !== "done" && s.status !== "cancelled") out.push(`<span class="chip stop">high</span>`);
  return out.join("");
}
function row(s, { check = false, href = null, showProject = true } = {}) {
  const d = dueInfo(s);
  const lead = check
    ? `<button type="button" class="check needs-net" data-act="check" data-key="${esc(s.key)}" aria-label="Mark ${esc(s.id || s.title)} done"><span class="box">${icon("check")}</span></button>`
    : `<span class="dot ${s.status === "done" ? "ok" : s.status === "cancelled" ? "" : s.type === "decision" ? "decide" : s.status === "blocked" || s.overdue_days ? "stop" : s.human ? "" : "agent"}"></span>`;
  return `<li class="row" data-key="${esc(s.key)}">
    <span class="lead">${lead}</span>
    <span class="id">${esc(s.id || "inbox")}</span>
    <span class="ttl"><a href="${esc(href || taskHref(s.key))}">${esc(s.title)}</a>${showProject ? `<span class="proj">${esc(s.project_name)}${s.human ? "" : " · " + esc(who(s))}</span>` : `<span class="proj">${esc(who(s))}</span>`}</span>
    <span class="end">${chips(s)}<span class="due ${d.cls}">${esc(d.text)}</span></span>
  </li>`;
}
const rows = (list, opts) => `<ul class="rows">${list.map((s) => row(s, opts)).join("")}</ul>`;

// ── Today ───────────────────────────────────────────────────────────────────
async function renderToday() {
  try { S.today = await api("/api/today"); } catch (e) { return errorBox(e, true); }
  const t = S.today;
  S.meta = { ...S.meta, ...t };
  updateCounts(t);
  $("#view-sub").textContent = fmtDay(t.today, true);
  const m = t.mine;
  const dec = t.decisions;
  const needToday = m.today.length + m.overdue.length;
  const bits = [];
  if (dec.count) bits.push(plural(dec.count, "decision", "decisions"));
  if (needToday) bits.push(plural(needToday, "task", "tasks"));
  if (t.waiting.length) bits.push(plural(t.waiting.length, "blocked agent", "blocked agents"));
  const greet = bits.length
    ? `<p class="greet"><b>${esc(t.owner_name)}</b>, ${bits.join(", ").replace(/, ([^,]*)$/, " and $1")} ${bits.length === 1 && (dec.count + needToday + t.waiting.length) === 1 ? "needs" : "need"} you.</p>`
    : `<p class="greet"><b>${esc(t.owner_name)}</b>, nothing needs you right now.</p>`;

  if (!t.projects && !dec.count && !needToday && !m.week.length) {
    return main(`${greet}<div class="sec"><div class="empty-big"><h2>No project yet</h2>
      <p>Start your first one in Claude Code with <code>/new-project</code>. It appears here as soon as its folder exists.</p>
      <button class="btn" data-act="copy" data-text="/new-project">Copy the command</button></div></div>`);
  }

  const decSec = dec.count
    ? `<section class="sec decide" aria-labelledby="h-dec">
        <div class="sec-head"><h2 id="h-dec">Decisions</h2><span class="meta">${dec.overdue ? `<b class="due over">${dec.overdue} overdue</b> · ` : ""}${dec.on_time} on time</span>
          <span class="end"><a class="btn hide-mobile" href="#/decisions">Open the stack ${icon("arrow")}</a></span></div>
        <ul class="rows">${dec.top.map((s, i) => row(s, { href: hashFor("decisions", s.key) }).replace('class="row"', `class="row${i === 0 ? " keep-mobile" : ""}"`)).join("")}</ul>
        ${dec.count > 3 ? `<div class="sec-foot muted hide-mobile">${dec.count - 3} more in the stack.</div>` : ""}
        <div class="mobile-cta"><a class="btn primary" href="${hashFor("decisions", dec.top[0].key)}">Start with the most urgent (${dec.count})</a></div>
      </section>`
    : `<section class="sec"><div class="sec-head"><h2>Decisions</h2></div><div class="sec-empty">Nothing waits for your decision. Agents keep working. <a href="#/activity">See what they did</a></div></section>`;

  const group = (title, list, cls, open) => list.length
    ? `<details class="group ${cls}" ${open ? "open" : ""}><summary>${title} <span class="n">${list.length}</span></summary>${rows(list, { check: true })}</details>` : "";
  const mineSec = `<section class="sec" aria-labelledby="h-mine">
      <div class="sec-head"><h2 id="h-mine">Your tasks</h2><span class="meta">Today ${m.today.length} · Overdue ${m.overdue.length} · This week ${m.week.length}</span></div>
      ${m.today.length ? rows(m.today, { check: true }) : `<div class="sec-empty">Nothing due today.${m.overdue.length ? ` ${plural(m.overdue.length, "overdue task waits", "overdue tasks wait")} below.` : ""}</div>`}
      ${group("Overdue", m.overdue, "over", m.overdue.length <= 3)}
      ${group("This week", m.week, "", m.today.length + m.overdue.length === 0)}
      ${group("Later or no date", m.later, "", false)}
    </section>`;

  const waitSec = t.waiting.length ? `<section class="sec" aria-labelledby="h-wait">
      <div class="sec-head"><h2 id="h-wait">Agents waiting on you</h2><span class="meta">${t.waiting.length}</span></div>
      ${t.waiting.map((s) => `<div class="wait-row" data-key="${esc(s.key)}">
        <div><span class="mono muted">${esc(s.id)}</span> <a href="${esc(taskHref(s.key))}">${esc(s.title)}</a> <span class="muted">· ${esc(s.project_name)} · ${esc(who(s))} agent is blocked</span></div>
        ${s.unblocking_action ? `<div class="why"><b>Needs:</b> ${esc(s.unblocking_action.replace(/\s+/g, " ").slice(0, 240))}</div>` : ""}
        ${s.unblocked_by_key ? `<div class="acts"><a class="btn" href="${esc(taskHref(s.unblocked_by_key))}">Open ${esc(s.unblocked_by)}</a></div>` : ""}
      </div>`).join("")}
    </section>` : "";

  const reviewSec = t.review.length ? `<section class="sec" aria-labelledby="h-rev">
      <div class="sec-head"><h2 id="h-rev">Ready for your review</h2><span class="meta">${t.review.length}</span></div>
      ${rows(t.review, { check: true })}</section>` : "";

  const stat = `<p class="statline"><span>${t.agents_working ? `<span class="pulse"></span> ${plural(t.agents_working, "agent", "agents")} working` : "No agent working right now"}</span>
    <span>${plural(t.closed_24h, "task", "tasks")} closed in the last 24 h · <a href="#/activity">Activity</a></span></p>`;

  main(`${greet}${decSec}${mineSec}${waitSec}${reviewSec}${stat}${errorsNote(t.errors)}`);
}
function errorsNote(errors) {
  if (!errors || !errors.length) return "";
  return `<details class="notice"><summary>${plural(errors.length, "file was", "files were")} skipped because they could not be read</summary><ul>${errors.map((e) => `<li><code>${esc(e)}</code></li>`).join("")}</ul></details>`;
}

// ── Decisions (stack) ───────────────────────────────────────────────────────
async function renderDecisions() {
  try { S.decisions = await api("/api/decisions"); } catch (e) { return errorBox(e, true); }
  const items = S.decisions.items;
  const want = S.route.rest;
  const i = want ? items.findIndex((s) => s.key === want) : -1;
  S.decIdx = i >= 0 ? i : Math.min(S.decIdx, Math.max(0, items.length - 1));
  drawStack();
}
function drawStack(tickCounter = false) {
  const items = S.decisions.items;
  S.armed = null;
  if (!items.length) {
    return main(`<div class="sec"><div class="empty-big"><h2>Nothing waits for your decision</h2><p>Agents keep working. New decisions appear here first.</p><a class="btn" href="#/activity">See what they did</a></div></div>`);
  }
  const cur = items[S.decIdx];
  const d = dueInfo(cur);
  const list = items.map((s, i) => {
    const di = dueInfo(s);
    return `<li class="row${i === S.decIdx ? " sel" : ""}" data-act="pick" data-i="${i}" ${i === S.decIdx ? 'aria-current="true"' : ""}>
      <span class="dot ${s.overdue_days ? "stop" : "decide"}"></span><span class="id">${esc(s.id)}</span>
      <span class="ttl"><span title="${esc(s.title)}">${esc(s.title.replace(/^decision:\s*/i, ""))}</span><span class="proj">${esc(s.project_name)}</span></span><span class="end"><span class="due ${di.cls}">${esc(di.text)}</span></span></li>`;
  }).join("");
  const links = (cur.links || []).map((l) => /^https?:/i.test(l.href)
    ? `<a class="chip" href="${esc(l.href)}" target="_blank" rel="noopener noreferrer">${esc(l.label)}</a>`
    : `<span class="chip" title="${esc(l.href)}">${esc(l.label)}</span>`).join("");
  main(`<div class="stack">
    <section class="sec stack-list" aria-label="Decision list">
      <div class="sec-head"><h2>Waiting</h2><span class="counter${tickCounter ? " tick" : ""}" aria-live="polite">${items.length}</span>
        <span class="meta">${S.decisions.overdue ? `${S.decisions.overdue} overdue` : "none overdue"}</span></div>
      <ul class="rows">${list}</ul>
    </section>
    <article class="slip" aria-labelledby="slip-title" data-key="${esc(cur.key)}">
      <div class="slip-head"><span class="chip decide">Decision</span><span class="mono">${esc(cur.id)}</span><span>${esc(cur.project_name)}</span>
        ${cur.due ? `<span class="due ${d.cls}">${d.cls === "over" ? esc(d.text) : "due " + esc(d.text)}</span>` : ""}
        <span class="pos">${S.decIdx + 1} / ${items.length}</span>
        <span class="only-mobile head-nav"><button type="button" class="icon-btn" data-act="prev" aria-label="Previous decision">${icon("back")}</button><button type="button" class="icon-btn" data-act="next" aria-label="Next decision">${icon("arrow")}</button></span></div>
      <div class="slip-body">
        <h2 id="slip-title">${esc(cur.title)}</h2>
        <div class="rec"><div class="rec-label">Recommendation</div>${cur.recommendation ? md(cur.recommendation) : '<p class="muted">No recommendation was written. Read the full task before deciding.</p>'}</div>
        ${cur.context ? `<div><div class="rec-label quiet">Context</div>${md(cur.context)}</div>` : ""}
        ${links ? `<div class="links">${links}</div>` : ""}
        ${cur.notes ? `<div><div class="rec-label quiet">Your earlier notes</div>${md(cur.notes)}</div>` : ""}
        <details class="full" data-key="${esc(cur.key)}"><summary class="link-btn">Full task</summary><div class="full-body muted">Loading…</div></details>
      </div>
      <div class="slip-foot">
        <label class="sr" for="dec-note">Comment, sent with the decision</label>
        <textarea id="dec-note" rows="1" placeholder="Comment (optional, sent with the decision)"></textarea>
        <div class="slip-acts">
          <button type="button" class="btn accept needs-net" data-act="decide" data-v="accept"><span class="lbl">Accept</span> <kbd class="hint">A</kbd></button>
          <button type="button" class="btn reject needs-net" data-act="decide" data-v="reject"><span class="lbl">Reject</span> <kbd class="hint">O</kbd></button>
          <button type="button" class="btn" data-act="skip">Skip <kbd class="hint">S</kbd></button>
          <span class="nav-keys"><button type="button" class="btn" data-act="prev" aria-label="Previous decision">${icon("back")}<kbd class="hint">K</kbd></button>
          <button type="button" class="btn" data-act="next" aria-label="Next decision"><kbd class="hint">J</kbd>${icon("arrow")}</button></span>
        </div>
      </div>
    </article></div>`);
  const want = hashFor("decisions", cur.key);
  if (location.hash !== want && !S.route.q.task) history.replaceState(null, "", want);
  S.route = parseHash();
}
function moveDecision(delta) {
  const n = S.decisions?.items.length || 0;
  if (!n) return;
  S.decIdx = (S.decIdx + delta + n) % n;
  drawStack();
}
function armOrCommit(kind) {
  const btn = $(`[data-act="decide"][data-v="${kind}"]`);
  if (!btn || S.offline) return;
  if (S.armed && S.armed.kind === kind && Date.now() < S.armed.until) return commitDecision(kind);
  $$('[data-act="decide"]').forEach((b) => { b.classList.remove("armed"); $(".lbl", b).textContent = b.dataset.v === "accept" ? "Accept" : "Reject"; });
  S.armed = { kind, until: Date.now() + ARM_MS };
  btn.classList.add("armed");
  $(".lbl", btn).textContent = kind === "accept" ? "Confirm accept" : "Confirm reject";
  setTimeout(() => {
    if (S.armed && S.armed.kind === kind && Date.now() >= S.armed.until) {
      S.armed = null; btn.classList.remove("armed");
      const l = $(".lbl", btn); if (l) l.textContent = kind === "accept" ? "Accept" : "Reject";
    }
  }, ARM_MS + 50);
}
function commitDecision(kind) {
  const items = S.decisions.items;
  const idx = S.decIdx;
  const cur = items[idx];
  const note = ($("#dec-note")?.value || "").trim();
  items.splice(idx, 1);
  S.decisions.count = items.length;
  if (cur.overdue_days) S.decisions.overdue = Math.max(0, S.decisions.overdue - 1);
  if (S.decIdx >= items.length) S.decIdx = Math.max(0, items.length - 1);
  drawStack(true);
  bumpCount("decisions", -1);
  const accepted = kind === "accept";
  closing({ action: "decide", key: cur.key, accepted, note }, {
    label: `${accepted ? "Accepted" : "Rejected"} ${cur.id}`,
    restore: () => {
      if (S.route.view !== "decisions") return;
      if (!S.decisions.items.some((s) => s.key === cur.key)) {
        S.decisions.items.splice(Math.min(idx, S.decisions.items.length), 0, cur);
        S.decisions.count = S.decisions.items.length;
        if (cur.overdue_days) S.decisions.overdue += 1;
      }
      S.decIdx = S.decisions.items.indexOf(cur);
      bumpCount("decisions", 1);
      drawStack(true);
      const ta = $("#dec-note"); if (ta) ta.value = note;
    },
  });
}

// ── Projects ────────────────────────────────────────────────────────────────
function healthDots(h) {
  const label = h >= 3 ? "on track" : h === 2 ? "needs attention" : "at risk";
  return `<span class="health h${h}" title="${label}">${[1, 2, 3].map((i) => `<i class="${i <= h ? "on" : ""}"></i>`).join("")}<span>${label}</span></span>`;
}
async function renderProjects() {
  if (S.route.rest) return renderProject(S.route.rest);
  try { S.projects = await api("/api/projects"); } catch (e) { return errorBox(e, true); }
  const items = S.projects.items;
  const tabs = `<div class="toolbar"><nav class="tabs" aria-label="Projects view"><a href="#/projects" aria-current="page">List</a><a href="#/tree">${icon("tree")}Tree</a></nav>
    ${S.projects.inbox_open ? `<span class="muted">${plural(S.projects.inbox_open, "open task", "open tasks")} in the inbox · <a href="#/tasks">All tasks</a></span>` : ""}</div>`;
  if (!items.length) {
    return main(`${tabs}<div class="sec"><div class="empty-big"><h2>No project yet</h2><p>Start your first one in Claude Code with <code>/new-project</code>.</p><button class="btn" data-act="copy" data-text="/new-project">Copy the command</button></div></div>`);
  }
  const num = (v, hot) => `<td class="num${hot && v ? " hot" : ""}">${v}</td>`;
  const table = `<table class="grid"><thead><tr><th>Project</th><th>Health</th><th class="num">Open</th><th class="num">Yours</th><th class="num">Decisions</th><th class="num">Blocked</th><th class="num">Overdue</th><th class="num">WIP</th><th>Last move</th></tr></thead><tbody>
    ${items.map((p) => `<tr data-key="${esc(p.slug)}"><td><a class="pname" href="#/projects/${esc(p.slug)}">${esc(p.name)}</a>${p.status !== "active" ? ` <span class="chip">${esc(p.status)}</span>` : ""}</td>
      <td>${healthDots(p.health)}</td>${num(p.open)}${num(p.yours)}${num(p.decisions)}${num(p.blocked, true)}${num(p.overdue, true)}
      <td class="num${p.wip > p.wip_limit ? " hot" : ""}">${p.wip}/${p.wip_limit}</td>
      <td class="muted">${esc(fmtStamp(p.last_move))}${p.last_owner ? " · " + esc(ROLE[p.last_owner] || p.last_owner) : ""}</td></tr>`).join("")}
    </tbody></table>`;
  const cards = `<div class="pcards">${items.map((p) => `<a class="pcard" href="#/projects/${esc(p.slug)}">
      <span class="pn">${esc(p.name)} ${healthDots(p.health)}</span>
      <span class="nums"><span><b>${p.open}</b> open</span><span><b>${p.yours}</b> yours</span><span><b class="${p.blocked ? "hot" : ""}">${p.blocked}</b> blocked</span><span><b class="${p.overdue ? "hot" : ""}">${p.overdue}</b> overdue</span><span>WIP <b>${p.wip}/${p.wip_limit}</b></span></span>
      <span class="muted">${esc(fmtStamp(p.last_move))}${p.last_title ? " · " + esc(p.last_title) : ""}</span></a>`).join("")}</div>`;
  main(`${tabs}<section class="sec">${table}${cards}</section>`);
}

function treeNode(n) {
  const kids = n.children || [];
  const cls = [n.human ? "human" : "", n.status === "blocked" ? "blocked" : "", ["done", "cancelled"].includes(n.status) ? "done" : "", n.ref ? "ref" : ""].join(" ");
  const d = dueInfo(n);
  const lead = n.type === "decision" ? '<span class="dot decide"></span>'
    : n.working ? '<span class="pulse"></span>'
    : n.human ? icon("you") : icon("agent");
  const extra = n.ref ? ' <span class="muted ref-note">(shown above)</span>' : n.cycle ? ' <span class="chip stop">cycle</span>' : "";
  return `<li>
    <div class="tnode">${kids.length ? `<button type="button" class="tog" data-act="tog" aria-expanded="true" aria-label="Collapse ${esc(n.id)}"></button>` : '<span class="spacer"></span>'}
      <a class="tk ${cls}" href="${esc(taskHref(n.key))}">${lead}<span class="mono">${esc(n.id)}</span><span class="t">${esc(n.title)}</span></a>${extra}
      <span class="who">${esc(who(n))}${d.text ? ` · <span class="due ${d.cls}">${esc(d.text)}</span>` : ""}</span></div>
    ${kids.length ? `<ul>${kids.map(treeNode).join("")}</ul>` : ""}
  </li>`;
}
function treeBlock(t, withLanes = true) {
  const chains = t.chains.length
    ? `<ul class="tree" aria-label="Dependencies">${t.chains.map(treeNode).join("")}</ul>`
    : '<div class="sec-empty">No task waits on another one.</div>';
  const lanes = withLanes && t.lanes.length ? `<div class="lanes">${t.lanes.map((l) => `<div class="lane"><h4>${esc(l.lane === "you" ? "You" : ROLE[l.lane] || l.lane)} · not linked</h4><div class="tk-wrap">
      ${l.tasks.map((n) => `<a class="tk-chip chip${n.overdue_days ? " stop" : n.type === "decision" ? " decide" : ""}" href="${esc(taskHref(n.key))}"><span class="mono">${esc(n.id)}</span> ${esc(n.title)}</a>`).join("")}</div></div>`).join("")}</div>` : "";
  const legend = `<div class="legend"><span><i class="h"></i>yours</span><span><i class="b"></i>blocked</span><span>${icon("agent")}agent</span><span>Children wait on their parent.</span></div>`;
  return chains + lanes + legend;
}
async function renderTree() {
  try { S.tree = await api("/api/tree"); } catch (e) { return errorBox(e, true); }
  const tabs = `<div class="toolbar"><nav class="tabs" aria-label="Projects view"><a href="#/projects">List</a><a href="#/tree" aria-current="page">${icon("tree")}Tree</a></nav>
    <span class="muted">What waits on what, per project.</span></div>`;
  if (!S.tree.projects.length) return main(`${tabs}<div class="sec"><div class="sec-empty">No open tasks in any project.</div></div>`);
  main(`${tabs}<section class="sec">${S.tree.projects.map((p, i) => `<details class="ptree" ${p.linked || i === 0 ? "open" : ""}>
      <summary><a class="pname" href="#/projects/${esc(p.slug)}">${esc(p.name)}</a><span class="meta">${p.linked} linked · ${p.open} open</span></summary>
      ${treeBlock(p)}</details>`).join("")}</section>`);
}

async function renderProject(slug) {
  try { S.project = await api(`/api/project/${encodeURIComponent(slug)}`); } catch (e) {
    return main(`<div class="sec"><div class="sec-empty">${e.status === 404 ? "This project does not exist." : "Could not load the project: " + esc(e.message)} <a href="#/projects">All projects</a></div></div>`);
  }
  const p = S.project;
  $("#view-sub").textContent = p.name;
  const phase = p.phase.current ? `${esc(p.phase.current.title.replace(/\s*\(current\)\s*/i, ""))} · ${p.phase.current.done}/${p.phase.current.done + p.phase.current.open} done` : '<span class="muted">No PLAN.md phases</span>';
  const full = p.wip >= p.wip_limit;
  const blockers = p.blockers.length ? p.blockers.map((s) => `<div class="wait-row"><div><span class="mono muted">${esc(s.id)}</span> <a href="${esc(taskHref(s.key))}">${esc(s.title)}</a> <span class="muted">· ${esc(who(s))}</span></div>
      ${s.unblocking_action ? `<div class="why"><b>Unblocking action:</b> ${esc(s.unblocking_action.replace(/\s+/g, " ").slice(0, 300))}</div>` : '<div class="why">No unblocking action written.</div>'}
      ${s.unblocked_by_key ? `<div class="acts"><a class="btn" href="${esc(taskHref(s.unblocked_by_key))}">Open ${esc(s.unblocked_by)}</a></div>` : ""}</div>`).join("")
    : '<div class="sec-empty">Nothing is blocked.</div>';
  const list = (title, items, opts, empty) => `<section class="sec"><div class="sec-head"><h2>${title}</h2><span class="meta">${items.length}</span></div>${items.length ? rows(items, opts) : `<div class="sec-empty">${empty}</div>`}</section>`;
  main(`<div class="phead"><a class="back" href="#/projects">${icon("back")}All projects</a>
      <h2>${esc(p.name)} ${p.status !== "active" ? `<span class="chip">${esc(p.status)}</span>` : ""}</h2>
      ${p.goal ? `<div class="muted">${md(p.goal.split("\n").slice(0, 2).join("\n"))}</div>` : ""}</div>
    <div class="pgrid"><div>
      <section class="sec"><div class="sec-head"><h2>Blocked</h2><span class="meta">${p.blockers.length}</span></div>${blockers}</section>
      ${p.decisions.length ? list("Decisions", p.decisions, { showProject: false }, "") : ""}
      <section class="sec"><div class="sec-head"><h2>Dependencies</h2><span class="meta">${p.tree.linked} of ${p.tree.open} open tasks are linked</span>
        <span class="end"><a class="link-btn" href="#/tree">Tree of all projects ${icon("arrow")}</a></span></div>${treeBlock(p.tree, false)}</section>
      ${list("Your tasks", p.yours, { check: true, showProject: false }, "Nothing on your list here.")}
      ${list("Agent tasks", p.agents, { showProject: false }, "No agent task open.")}
    </div><div>
      <section class="sec"><div class="sec-head"><h2>Status</h2></div><dl class="facts">
        ${p.success ? `<dt>Success</dt><dd>${md(p.success)}</dd>` : ""}
        <dt>Phase</dt><dd>${phase}</dd>
        <dt>WIP</dt><dd><span class="meter${full ? " full" : ""}"><span class="bar"><i data-w="${Math.min(100, Math.round((100 * p.wip) / Math.max(1, p.wip_limit)))}"></i></span><b class="mono">${p.wip}/${p.wip_limit}</b>${full ? '<span class="muted">limit reached</span>' : ""}</span></dd>
      </dl></section>
      <section class="sec"><div class="sec-head"><h2>Recent log</h2></div>${p.log.length ? `<ul class="log">${p.log.map((l) => `<li><time>${esc(fmtStamp(l.when.replace(" ", "T")))}</time><span>${esc(l.text)}</span></li>`).join("")}</ul>` : '<div class="sec-empty">LOG.md is empty.</div>'}</section>
      ${p.recent_closed.length ? list("Closed in the last 7 days", p.recent_closed, { showProject: false }, "") : ""}
    </div></div>`);
}

// ── Activity ────────────────────────────────────────────────────────────────
function markVisit() {
  // "since your last visit": remember the previous visit, refresh the current one later
  if (S.visitMarked) return;
  S.visitMarked = true;
  setTimeout(() => localStorage.setItem(LS.visit, localIso()), 10000);
}
async function renderActivity() {
  const range = S.route.q.range || (S.lastVisit ? "visit" : "24h");
  const now = new Date();
  let since = "";
  if (range === "visit" && S.lastVisit) since = S.lastVisit;
  else if (range === "7d") since = localIso(new Date(now - 7 * 86400000));
  else if (range === "all") since = "2000-01-01T00:00";
  else since = localIso(new Date(now - 86400000));
  try { S.activity = await api(`/api/activity?since=${encodeURIComponent(since)}${range === "all" ? "&archive=1" : ""}`); } catch (e) { return errorBox(e, true); }
  const a = S.activity;
  const tab = (r, label) => `<a href="${hashFor("activity", "", { range: r })}" ${r === range ? 'aria-current="page"' : ""}>${label}</a>`;
  const heading = range === "visit" ? `Since your last visit (${esc(fmtStamp(S.lastVisit))})`
    : range === "7d" ? "Last 7 days" : range === "all" ? "Everything" : "Last 24 hours";
  const max = Math.max(1, ...a.groups.map((g) => g.items.length));
  const kindIcon = { agent: "agent", you: "you", decided: "decide", cancelled: "close" };
  const kindLabel = { agent: "done by an agent", you: "done by you", decided: "decided by you", cancelled: "cancelled" };
  const groups = a.groups.map((g, gi) => `<details class="act-proj" ${gi < 2 ? "open" : ""}><summary>
      <span class="pn">${esc(g.name || "Inbox")}</span><span class="n">${g.items.length}</span>
      <span class="act-bar-track"><span class="act-bar" data-w="${Math.round((100 * g.items.length) / max)}"></span></span>
      <span class="split">${g.done} done${g.cancelled ? ` · ${g.cancelled} cancelled` : ""}</span></summary>
      ${g.items.map((s) => `<div class="act-item k-${s.kind}" title="${kindLabel[s.kind]}">${icon(kindIcon[s.kind])}<span class="mono muted">${esc(s.id)}</span>
        <a class="t" href="${esc(taskHref(s.key))}">${esc(s.title)}${s.kind === "decided" ? ` <span class="chip ${s.decision === "accepted" ? "ok" : "stop"}">${esc(s.decision)}</span>` : ""}</a>
        <time>${esc(fmtStamp(s.when))}</time></div>`).join("")}
    </details>`).join("");
  main(`<div class="toolbar"><nav class="tabs" aria-label="Time range">${S.lastVisit ? tab("visit", "Since last visit") : ""}${tab("24h", "24 hours")}${tab("7d", "7 days")}${tab("all", "Everything")}</nav></div>
    <div class="act-head"><h2>${heading}: ${plural(a.total, "task closed", "tasks closed")}</h2>
      <span class="muted">Your decisions: ${a.accepted} accepted, ${a.rejected} rejected${a.clamped ? " · showing the last 7 days" : ""}</span></div>
    ${a.working.length ? `<section class="sec"><div class="sec-head"><h2>Working now</h2><span class="meta">${a.working.length}</span></div>${rows(a.working)}</section>` : ""}
    <section class="sec">${groups || '<div class="sec-empty">Nothing closed in this period. <a href="' + hashFor("activity", "", { range: "7d" }) + '">Look at the last 7 days</a></div>'}</section>`);
}

// ── All tasks ───────────────────────────────────────────────────────────────
async function renderTasks() {
  const q = S.route.q;
  const scope = ["open", "recent", "all"].includes(q.scope) ? q.scope : "open";
  const whoF = ["mine", "agents"].includes(q.who) ? q.who : "all";
  try { S.tasks = await api(`/api/tasks?scope=${scope}`); } catch (e) { return errorBox(e, true); }
  const needle = (q.q || "").toLowerCase();
  let items = S.tasks.items.filter((s) => (whoF === "all" || (whoF === "mine") === s.human));
  if (needle) items = items.filter((s) => `${s.id} ${s.title} ${s.project_name} ${s.owner}`.toLowerCase().includes(needle));
  const shown = items.slice(0, 400);
  const tab = (k, v, label, cur) => `<a href="${hashFor("tasks", "", { ...q, [k]: v, task: "" })}" ${cur === v ? 'aria-current="page"' : ""}>${label}</a>`;
  $("#search").value = q.q || "";
  main(`<div class="toolbar">
      <nav class="tabs" aria-label="Whose tasks">${tab("who", "all", "Everyone", whoF)}${tab("who", "mine", "Mine", whoF)}${tab("who", "agents", "Agents", whoF)}</nav>
      <nav class="tabs" aria-label="Which tasks">${tab("scope", "open", "Open", scope)}${tab("scope", "recent", "Last 7 days", scope)}${tab("scope", "all", "With archive", scope)}</nav>
      <span class="muted">${plural(items.length, "task", "tasks")}${needle ? ` matching “${esc(q.q)}”` : ""}</span></div>
    <section class="sec">${shown.length ? rows(shown, { check: false }) : '<div class="sec-empty">No task matches.</div>'}
      ${items.length > shown.length ? `<div class="sec-foot muted">Showing the first ${shown.length}. Narrow the search to see the rest.</div>` : ""}</section>`);
}

// ── drawer (task detail and actions) ────────────────────────────────────────
async function openDrawer(key) {
  const wrap = $("#drawer-wrap");
  const dr = $("#drawer");
  if (S.drawer?.key === key && !wrap.hidden) return;
  S.editing = false;
  S.closingAsk = false;
  wrap.hidden = false;
  document.body.style.overflow = "hidden";
  dr.innerHTML = `<div class="dr-head"><span>Loading…</span><button class="icon-btn x" data-close="drawer" aria-label="Close">${icon("close")}</button></div>`;
  try {
    S.drawer = await api(`/api/task/${key.split("/").map(encodeURIComponent).join("/")}`);
  } catch (e) {
    dr.innerHTML = `<div class="dr-head"><span>${e.status === 404 ? "This task does not exist any more." : esc(e.message)}</span><button class="icon-btn x" data-close="drawer" aria-label="Close">${icon("close")}</button></div>`;
    return;
  }
  drawDrawer();
  dr.focus();
}
function drawDrawer() {
  const t = S.drawer;
  const dr = $("#drawer");
  const d = dueInfo(t);
  const closed = ["done", "cancelled"].includes(t.status);
  const statusChip = t.status === "blocked" ? "stop" : t.status === "done" ? "ok" : t.working ? "agent" : "";
  const refLink = (id) => {
    const k = `${t.project}/${id}`;
    return t.project ? `<a href="${esc(hashFor(S.route.view, S.route.rest, { ...S.route.q, task: k }))}" class="mono">${esc(id)}</a>` : esc(id);
  };
  const waits = [...new Set([...(t.blocked_by || []), ...(t.unblocked_by ? [t.unblocked_by] : [])])];
  const evidence = t.evidence ? (/^https?:\/\//i.test(t.evidence) ? `<a href="${esc(t.evidence)}" target="_blank" rel="noopener noreferrer">${esc(t.evidence)}</a>` : `<code>${esc(t.evidence)}</code>`) : "";
  const isDecision = t.type === "decision";
  const A = t.actions;
  let acts = "";
  if (t.archived) acts = `<p class="reason">${esc(t.archived_reason)}</p>`;
  else if (S.editing) acts = "";
  else {
    const primary = isDecision && A.decide
      ? `<button class="btn accept needs-net" data-act="d-decide" data-v="accept"><span class="lbl">Accept</span></button><button class="btn reject needs-net" data-act="d-decide" data-v="reject"><span class="lbl">Reject</span></button>`
      : A.done ? `<button class="btn accept needs-net" data-act="d-done">${icon("check")}Mark done</button>` : "";
    acts = `<div class="dr-done" hidden><label class="field"><span>Evidence: a file path, a link or a test result</span><input id="d-evidence" autocomplete="off" value="${esc(t.evidence)}" placeholder="materials/report.md, https://…, 12 tests passed"></label></div>
      <label class="sr" for="d-note">Comment</label><textarea id="d-note" rows="2" placeholder="Comment (optional)"></textarea>
      <div class="dr-acts">${primary}
        <button class="btn needs-net" data-act="d-note">Add note</button>
        ${A.cancel ? `<button class="btn reject needs-net" data-act="d-cancel">${S.closingAsk ? "Confirm cancel" : "Cancel task"}</button>` : ""}
        <span class="sp"></span>
        ${A.edit ? '<button class="btn" data-act="d-edit">Edit</button>' : ""}
        ${A.run_now ? `<button class="btn needs-net" data-act="d-run">${icon("play")}Run now</button>` : ""}
      </div>`;
  }
  const body = S.editing ? `<form class="edit" id="edit-form">
      <label class="field"><span>Title</span><input name="title" value="${esc(t.title)}" maxlength="200" required></label>
      <div class="row-fields"><label class="field"><span>Priority</span><select name="priority">${["high", "normal", "low"].map((p) => `<option ${p === t.priority ? "selected" : ""}>${p}</option>`).join("")}</select></label>
        <label class="field"><span>Due</span><input type="date" name="due" value="${esc(t.due)}"></label><span></span></div>
      <label class="field"><span>Content (Markdown, without the frontmatter)</span><textarea name="body">${esc(t.body.replace(/^\n+/, ""))}</textarea></label>
      <div class="dr-acts"><button type="submit" class="btn primary needs-net">Save</button><button type="button" class="btn" data-act="d-edit-cancel">Discard changes</button></div>
    </form>` : `
      <h2 id="drawer-title">${esc(t.title)}</h2>
      <dl class="facts flush">
        <dt>Owner</dt><dd>${esc(who(t))}${t.autonomy === "ask" ? ' <span class="chip">asks first</span>' : ""}</dd>
        ${t.due ? `<dt>Due</dt><dd><span class="due ${d.cls}">${esc(fmtDay(t.due))}${d.cls === "over" ? " · " + esc(d.text) : ""}</span></dd>` : ""}
        <dt>Priority</dt><dd>${esc(t.priority)}</dd>
        ${waits.length ? `<dt>Waits on</dt><dd>${waits.map(refLink).join(", ")}</dd>` : ""}
        ${t.waiting_on_this.length ? `<dt>Unblocks</dt><dd>${t.waiting_on_this.map((k) => refLink(k.split("/")[1])).join(", ")}</dd>` : ""}
        ${evidence ? `<dt>Evidence</dt><dd>${evidence}</dd>` : ""}
        ${t.decision ? `<dt>Decision</dt><dd><span class="chip ${t.decision === "accepted" ? "ok" : "stop"}">${esc(t.decision)}</span></dd>` : ""}
        <dt>File</dt><dd><code>${esc(t.rel_path)}</code></dd>
      </dl>
      ${!t.archived && !A.run_now && !t.human && !isDecision && !closed ? `<p class="reason">Run now is not available: ${esc(t.run_now_reason)}</p>` : ""}
      ${md(cleanBody(t.body, t.title))}`;
  dr.innerHTML = `<div class="dr-head"><span class="chip ${isDecision ? "decide" : statusChip}">${esc(isDecision ? "decision" : t.type === "review" ? "review" : t.status.replace("_", " "))}</span>
      <span class="mono">${esc(t.id || "inbox")}</span><span>${esc(t.project_name)}</span>${t.working ? '<span class="chip agent"><span class="pulse"></span>agent working</span>' : ""}
      <button class="icon-btn x" data-close="drawer" aria-label="Close">${icon("close")}</button></div>
    <div class="dr-body">${body}</div>
    ${acts ? `<div class="dr-foot">${acts}</div>` : ""}`;
}
function closeDrawer(updateHash = true) {
  const wrap = $("#drawer-wrap");
  if (wrap.hidden) return;
  wrap.hidden = true;
  document.body.style.overflow = "";
  S.drawer = null;
  if (updateHash && S.route.q.task) {
    const q = { ...S.route.q }; delete q.task;
    history.replaceState(null, "", hashFor(S.route.view, S.route.rest, q));
    S.route = parseHash();
  }
}
async function drawerAction(kind, btn) {
  const t = S.drawer;
  if (!t) return;
  const note = ($("#d-note")?.value || "").trim();
  if (kind === "note") {
    if (!note) { $("#d-note").focus(); return toast("Write the note first.", { error: true }); }
    return immediate({ action: "note", key: t.key, note }, btn, true);
  }
  if (kind === "run") return immediate({ action: "run-now", key: t.key }, btn, true);
  if (kind === "done") {
    const box = $(".dr-done");
    const ev = $("#d-evidence");
    if (box.hidden && !t.evidence) { box.hidden = false; ev.focus(); btn.innerHTML = `${icon("check")}Confirm done`; return; }
    const evidence = ev.value.trim();
    if (!evidence && !t.evidence) { ev.focus(); return toast("Add evidence before closing: a file path, a link or a test result.", { error: true }); }
    return closeFromDrawer({ action: "done", key: t.key, evidence, note }, `Marked ${t.id || "task"} done`);
  }
  if (kind === "cancel") {
    if (!S.closingAsk) { S.closingAsk = true; btn.textContent = "Confirm cancel"; return; }
    return closeFromDrawer({ action: "cancel", key: t.key, note }, `Cancelled ${t.id || "task"}`);
  }
}
function closeFromDrawer(body, label) {
  const key = body.key;
  closeDrawer();
  const restoreRows = hideRows(key);
  bumpCount("today", -1);
  closing(body, { label, restore: () => { restoreRows(); bumpCount("today", 1); }, after: () => softRefresh() });
}
function hideRows(key) {
  const els = $$(`[data-key="${CSS.escape(key)}"]`, $("#main"));
  els.forEach((el) => { el.hidden = true; const nx = el.nextElementSibling; if (nx?.classList.contains("inline-done")) nx.remove(); });
  return () => els.forEach((el) => { el.hidden = false; });
}
async function immediate(body, btn, reopen) {
  if (btn) btn.disabled = true;
  try {
    const res = await post("/api/actions", body);
    toast(res.message || "Saved.");
    if (reopen && S.drawer) { const k = S.drawer.key; S.drawer = null; await openDrawer(k); }
    softRefresh();
  } catch (err) {
    toast(err.message, { error: true, ms: 9000 });
  } finally { if (btn) btn.disabled = false; }
}

// inline "done" on a row (Today, project page)
function inlineDone(btn) {
  const li = btn.closest(".row");
  const key = btn.dataset.key;
  if (li.nextElementSibling?.classList.contains("inline-done")) { li.nextElementSibling.querySelector("input").focus(); return; }
  const box = document.createElement("li");
  box.className = "inline-done";
  box.innerHTML = `<label class="sr" for="ev-${esc(key)}">Evidence</label><input id="ev-${esc(key)}" placeholder="Evidence: a link, a file or one line on what happened" autocomplete="off">
    <button type="button" class="btn accept needs-net" data-act="inline-ok" data-key="${esc(key)}">Mark done</button><button type="button" class="btn" data-act="inline-no">Not yet</button>`;
  li.after(box);
  const input = $("input", box);
  input.focus();
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $('[data-act="inline-ok"]', box).click(); } if (e.key === "Escape") box.remove(); });
}
function inlineOk(btn) {
  const box = btn.closest(".inline-done");
  const evidence = $("input", box).value.trim();
  if (!evidence) { $("input", box).focus(); return toast("Add evidence before closing: a link, a file or a short result.", { error: true }); }
  const key = btn.dataset.key;
  box.remove();
  const restore = hideRows(key);
  bumpCount("today", -1);
  const id = key.split("/")[1];
  closing({ action: "done", key, evidence }, { label: `Marked ${/^[A-Z]-\d+$/.test(id) ? id : "task"} done`, restore: () => { restore(); bumpCount("today", 1); }, after: () => softRefresh() });
}

// ── new task / idea ─────────────────────────────────────────────────────────
async function openNew() {
  const dlg = $("#new-dialog");
  const form = $("#new-form");
  form.reset();
  $("#new-error").hidden = true;
  try {
    const p = S.projects || (S.projects = await api("/api/projects"));
    const sel = form.elements.project;
    sel.innerHTML = '<option value="">Inbox (no project)</option>' + p.items.map((x) => `<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("");
    if (S.route.view === "projects" && S.route.rest) sel.value = S.route.rest;
  } catch (_) { /* inbox still works */ }
  syncNewKind();
  dlg.showModal();
  form.elements.title.focus();
}
function syncNewKind() {
  const form = $("#new-form");
  const kind = form.elements.kind.value;
  $$("[data-for]", form).forEach((el) => { el.hidden = (el.dataset.for === "task" && kind === "idea") || (el.dataset.for === "agent" && kind !== "agent"); });
  $("#new-help").textContent = kind === "agent" ? "The queue picks agent tasks up on its next run. With a project, the task gets the next free ID there."
    : kind === "human" ? "Lands on your list in Today. Keep it under 15 minutes, or split it."
      : "Saved to the ideas folder. The CEO agent can turn it into a project later.";
}
async function submitNew(e) {
  e.preventDefault();
  const form = $("#new-form");
  const f = form.elements;
  const kind = f.kind.value;
  const body = kind === "idea"
    ? { kind: "idea", title: f.title.value, details: f.details.value }
    : { kind: "task", title: f.title.value, details: f.details.value, project: f.project.value, owner: kind === "human" ? "human" : f.owner.value, priority: f.priority.value, due: f.due.value };
  const btn = $("#new-submit");
  btn.disabled = true; btn.textContent = "Creating…";
  try {
    const res = await post("/api/create", body);
    $("#new-dialog").close();
    toast(res.message, res.key ? { action: () => go(hashFor(S.route.view, S.route.rest, { ...S.route.q, task: res.key })), actionLabel: "Open", ms: 7000 } : {});
    softRefresh();
  } catch (err) {
    const el = $("#new-error"); el.textContent = err.message; el.hidden = false;
  } finally { btn.disabled = false; btn.textContent = "Create"; }
}

// ── counts and refresh ──────────────────────────────────────────────────────
function updateCounts(t) {
  const set = (k, v) => $$(`[data-count="${k}"]`).forEach((el) => { el.textContent = v ? String(v) : ""; });
  set("today", t.mine.today.length + t.mine.overdue.length + t.review.length);
  set("decisions", t.decisions.count);
  set("activity", t.closed_24h);
}
function bumpCount(k, d) {
  $$(`[data-count="${k}"]`).forEach((el) => { const v = Math.max(0, (parseInt(el.textContent, 10) || 0) + d); el.textContent = v ? String(v) : ""; });
}
async function refreshCounts() {
  try { const t = await api("/api/today"); S.today = t; updateCounts(t); } catch (_) { /* offline bar */ }
}
let softTimer = null;
function softRefresh() {
  clearTimeout(softTimer);
  softTimer = setTimeout(async () => {
    if (S.armed || S.editing) return;
    const def = VIEWS[S.route.view] || VIEWS.today;
    const y = window.scrollY;
    await def.render();
    window.scrollTo(0, y);
    if (S.route.view !== "today") refreshCounts();
  }, 300);
}
function idle() {
  const a = document.activeElement;
  return !S.armed && !S.editing && !S.lastUndo && $("#drawer-wrap").hidden && !$("#new-dialog").open
    && !(a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) && !$(".inline-done");
}

// ── keyboard ────────────────────────────────────────────────────────────────
function listRows() { return $$("#main .row[data-key], #main .stack-list .row").filter((r) => !r.hidden && r.offsetParent !== null); }
function moveSel(delta) {
  if (S.route.view === "decisions") return moveDecision(delta);
  const list = listRows();
  if (!list.length) return;
  S.sel = Math.max(0, Math.min(list.length - 1, S.sel + delta));
  list.forEach((r, i) => r.classList.toggle("sel", i === S.sel));
  list[S.sel].scrollIntoView({ block: "nearest" });
}
function onKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
  if (e.key === "Escape") {
    if (!$("#drawer-wrap").hidden) { closeDrawer(); return; }
    if (typing) { e.target.blur(); return; }
    if (S.armed) { S.armed = null; drawStack(); }
    return;
  }
  if (typing || $("#new-dialog").open || $("#keys-dialog").open) return;
  const k = e.key.toLowerCase();
  if (S.gAt && Date.now() - S.gAt < 1200) {
    S.gAt = 0;
    const map = { d: "#/today", e: "#/decisions", p: "#/projects", a: "#/activity", t: "#/tasks" };
    if (map[k]) { e.preventDefault(); go(map[k]); }
    return;
  }
  const inStack = S.route.view === "decisions" && $("#drawer-wrap").hidden && S.decisions?.items.length;
  if (k === "g") { S.gAt = Date.now(); return; }
  if (k === "/") { e.preventDefault(); return focusSearch(); }
  if (k === "n") { e.preventDefault(); return openNew(); }
  if (k === "?") { e.preventDefault(); return $("#keys-dialog").showModal(); }
  if (k === "z" && S.lastUndo && Date.now() < S.lastUndo.until) { e.preventDefault(); return S.lastUndo.undo(); }
  if (k === "j") { e.preventDefault(); return moveSel(1); }
  if (k === "k") { e.preventDefault(); return moveSel(-1); }
  if (inStack) {
    if (k === "a") { e.preventDefault(); return armOrCommit("accept"); }
    if (k === "o") { e.preventDefault(); return armOrCommit("reject"); }
    if (k === "s") { e.preventDefault(); return moveDecision(1); }
    if (k === "c") { e.preventDefault(); return $("#dec-note")?.focus(); }
    if (k === "enter" && S.armed) { e.preventDefault(); return commitDecision(S.armed.kind); }
  }
  if (k === "enter" && S.sel >= 0) {
    const r = listRows()[S.sel];
    const a = r && $("a", r);
    if (a) { e.preventDefault(); a.click(); }
  }
}
function focusSearch() {
  const form = $("#search-form");
  form.classList.add("open");
  $("#search").focus();
}

// ── events ──────────────────────────────────────────────────────────────────
function onClick(e) {
  const close = e.target.closest("[data-close]");
  if (close) {
    const what = close.dataset.close;
    if (what === "drawer") closeDrawer();
    if (what === "new") $("#new-dialog").close();
    if (what === "keys") $("#keys-dialog").close();
    return;
  }
  const el = e.target.closest("[data-act]");
  if (!el) return;
  const act = el.dataset.act;
  switch (act) {
    case "check": return inlineDone(el);
    case "inline-ok": return inlineOk(el);
    case "inline-no": return el.closest(".inline-done").remove();
    case "pick": S.decIdx = Number(el.dataset.i); return drawStack();
    case "decide": return armOrCommit(el.dataset.v);
    case "skip": case "next": return moveDecision(1);
    case "prev": return moveDecision(-1);
    case "reload": return softRefresh();
    case "tog": {
      const li = el.closest("li");
      const collapsed = li.toggleAttribute("data-collapsed");
      el.setAttribute("aria-expanded", String(!collapsed));
      return;
    }
    case "copy": navigator.clipboard?.writeText(el.dataset.text).then(() => toast("Copied.")); return;
    case "d-done": return drawerAction("done", el);
    case "d-cancel": return drawerAction("cancel", el);
    case "d-note": return drawerAction("note", el);
    case "d-run": return drawerAction("run", el);
    case "d-edit": S.editing = true; return drawDrawer();
    case "d-edit-cancel": S.editing = false; return drawDrawer();
    case "d-decide": return drawerDecide(el);
    default: return undefined;
  }
}
function drawerDecide(btn) {
  const t = S.drawer;
  const kind = btn.dataset.v;
  if (!(S.armed && S.armed.kind === kind && S.armed.drawer && Date.now() < S.armed.until)) {
    $$('[data-act="d-decide"]').forEach((b) => b.classList.remove("armed"));
    S.armed = { kind, until: Date.now() + ARM_MS, drawer: true };
    btn.classList.add("armed");
    $(".lbl", btn).textContent = kind === "accept" ? "Confirm accept" : "Confirm reject";
    setTimeout(() => { if (S.armed?.drawer && Date.now() >= S.armed.until) S.armed = null; }, ARM_MS + 50);
    return;
  }
  S.armed = null;
  const note = ($("#d-note")?.value || "").trim();
  closeFromDrawer({ action: "decide", key: t.key, accepted: kind === "accept", note }, `${kind === "accept" ? "Accepted" : "Rejected"} ${t.id}`);
  bumpCount("decisions", -1);
}
async function onSubmit(e) {
  if (e.target.id === "new-form") return submitNew(e);
  if (e.target.id === "search-form") {
    e.preventDefault();
    const q = $("#search").value.trim();
    $("#search-form").classList.remove("open");
    return go(hashFor("tasks", "", { q }));
  }
  if (e.target.id === "edit-form") {
    e.preventDefault();
    const f = e.target.elements;
    const t = S.drawer;
    const btn = $('button[type="submit"]', e.target);
    btn.disabled = true;
    try {
      const res = await post("/api/actions", { action: "edit", key: t.key, mtime_ns: t.mtime_ns, title: f.title.value, priority: f.priority.value, due: f.due.value, body: f.body.value });
      toast(res.message);
      S.editing = false;
      const k = t.key; S.drawer = null; await openDrawer(k);
      softRefresh();
    } catch (err) {
      toast(err.message, { error: true, ms: 9000 });
      btn.disabled = false;
    }
  }
  return undefined;
}

// swipe between decisions on touch screens (buttons do the same)
let touchX = null;
document.addEventListener("touchstart", (e) => { if (e.target.closest(".slip-body")) touchX = e.touches[0].clientX; }, { passive: true });
document.addEventListener("touchend", (e) => {
  if (touchX === null) return;
  const dx = e.changedTouches[0].clientX - touchX;
  touchX = null;
  if (Math.abs(dx) > 70) moveDecision(dx < 0 ? 1 : -1);
}, { passive: true });

// lazy "Full task" in the stack
document.addEventListener("toggle", async (e) => {
  const det = e.target;
  if (!(det instanceof HTMLDetailsElement) || !det.classList.contains("full") || !det.open || det.dataset.loaded) return;
  det.dataset.loaded = "1";
  try {
    const t = await api(`/api/task/${det.dataset.key.split("/").map(encodeURIComponent).join("/")}`);
    $(".full-body", det).innerHTML = md(t.body);
  } catch (err) { $(".full-body", det).textContent = `Could not load: ${err.message}`; }
}, true);

// ── theme ───────────────────────────────────────────────────────────────────
function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
  $("#theme-label").textContent = `Theme: ${mode || "auto"}`;
}
function cycleTheme() {
  const order = ["auto", "light", "dark"];
  const cur = localStorage.getItem(LS.theme) || "auto";
  const next = order[(order.indexOf(cur) + 1) % order.length];
  localStorage.setItem(LS.theme, next);
  applyTheme(next);
}

// ── boot ────────────────────────────────────────────────────────────────────
async function boot() {
  const qsTheme = new URLSearchParams(location.search).get("theme");
  applyTheme(qsTheme || localStorage.getItem(LS.theme) || "auto");
  S.lastVisit = localStorage.getItem(LS.visit);
  document.addEventListener("click", onClick);
  document.addEventListener("submit", onSubmit);
  document.addEventListener("keydown", onKey);
  $("#new-form").addEventListener("change", (e) => { if (e.target.name === "kind") syncNewKind(); });
  $("#new-btn").addEventListener("click", openNew);
  $("#theme-btn").addEventListener("click", cycleTheme);
  $("#keys-btn").addEventListener("click", () => $("#keys-dialog").showModal());
  $("#search-mobile").addEventListener("click", focusSearch);
  $("#search").addEventListener("blur", () => setTimeout(() => $("#search-form").classList.remove("open"), 150));
  $("#drawer").addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = $$('a[href], button:not([disabled]), input, textarea, select', $("#drawer")).filter((x) => x.offsetParent !== null);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  window.addEventListener("hashchange", route);
  try {
    S.meta = await api("/api/meta");
    $("#brand-name").textContent = S.meta.product;
    document.title = `${S.meta.owner_name} · ${S.meta.product}`;
  } catch (_) { /* offline bar shows */ }
  await route();
  if (S.route.view !== "today") refreshCounts();
  setInterval(() => { if (document.visibilityState === "visible" && idle()) softRefresh(); }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && idle()) softRefresh(); });
}
boot();
