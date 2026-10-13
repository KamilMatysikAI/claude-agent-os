// Agent panel front end. Vanilla JS modules, no build step, no network beyond this server.
// Screens: Today, Decisions (stack), Projects (+ project page), Tree, Activity, All tasks.
// Every text goes through i18n.js (English and Polish dictionaries).
// Every write goes through /api/actions. Closing actions return a pending id and are
// applied by the server after 5 s, so "Undo" is real, not cosmetic.

import { initI18n, setLang, getLang, t, tn, has, joinList, applyStatic, parseDay, fmtDay, fmtDate, locale } from "./i18n.js";
import { mountTree } from "./tree.js";

const UNDO_MS = 5000;
const ARM_MS = 3000;
const REFRESH_MS = 60000;
const LS = { theme: "agentos.theme", visit: "agentos.lastVisit", stackFilter: "agentos.stackFilter", stackGroup: "agentos.stackGroup" };

const S = {
  meta: null, today: null, decisions: null, projects: null, project: null,
  activity: null, tasks: null, route: { view: "today", rest: "", q: {} },
  decIdx: 0, armed: null, lastUndo: null, lastOk: null, offline: false, sel: -1,
  drawer: null, editing: false, closingAsk: false, lastVisit: null, gAt: 0, tree: null,
  stackFilter: "all", stackGroup: "due", prevCount: null,
};

// ── helpers ─────────────────────────────────────────────────────────────────
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (name, cls = "") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const ls = {
  get: (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } },
};

function localIso(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function todayIso() { return S.meta?.today || localIso().slice(0, 10); }
function dayDiff(iso) { return Math.round((parseDay(iso) - parseDay(todayIso())) / 86400000); }
/** "today 14:20", "yesterday 09:10", "Sat 10 Oct 22:40" */
function fmtStamp(iso) {
  if (!iso) return "";
  const time = iso.length > 10 ? iso.slice(11, 16) : "";
  const day = iso.slice(0, 10);
  const diff = dayDiff(day);
  const d = diff === 0 ? t("date.today") : diff === -1 ? t("date.yesterday") : fmtDay(day);
  return time ? `${d} ${time}` : d;
}
function dueInfo(s) {
  // a closed task shows when it closed; its old due date ("tomorrow") would mislead
  if (s.closed && (s.status === "done" || s.status === "cancelled")) {
    return { text: t(s.status === "cancelled" ? "due.cancelled_on" : "due.closed_on", { date: fmtDay(s.closed) }), cls: "" };
  }
  if (!s.due) return { text: "", cls: "" };
  if (s.overdue_days > 0) return { text: tn("due.overdue", s.overdue_days), cls: "over" };
  const diff = dayDiff(s.due);
  if (diff === 0) return { text: t("date.today"), cls: "today" };
  if (diff === 1) return { text: t("date.tomorrow"), cls: "" };
  return { text: fmtDay(s.due), cls: "" };
}
const ROLES = ["ceo", "soft", "web", "copy", "marketing", "research"];
function roleName(r) { return ROLES.includes(r) ? t(`role.${r}`) : (r || t("role.unassigned")); }
const who = (s) => (s.human ? t("role.you") : roleName(s.owner));
const statusName = (st) => (has(`status.${st}`) ? t(`status.${st}`) : st);
const prioName = (p) => (has(`prio.${p}`) ? t(`prio.${p}`) : p);
const decisionName = (d) => (has(`decision.${d}`) ? t(`decision.${d}`) : d);
const projName = (s) => (s.project ? s.project_name : t("common.inbox"));

/** Server messages come with a code; the dictionary has `srv.<code>`, else the English text. */
function srvText(code, params, english) {
  if (code && has(`srv.${code}`)) {
    const p = { ...(params || {}) };
    if (p.state) p.state = statusName(p.state);
    return t(`srv.${code}`, p);
  }
  return english || "";
}

// contract headings in task files stay English on disk; the panel shows them translated
const HEADINGS = {
  "goal": "hdr.goal", "context": "hdr.context", "steps": "hdr.steps", "definition of done": "hdr.dod",
  "for approval": "hdr.for_approval", "unblocking action": "hdr.unblocking", "owner notes": "hdr.owner_notes",
  "progress log": "hdr.progress_log", "success criteria": "hdr.success", "constraints": "hdr.constraints",
  "out of scope": "hdr.out_of_scope",
};
function heading(text) {
  const k = HEADINGS[text.trim().toLowerCase()];
  return k ? t(k) : text;
}

// one line of text with `code` and **bold**, escaped first
const inlineMd = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

// tiny, safe markdown: escape first, then a small subset
function md(text) {
  if (!text) return "";
  const inline = (s) => esc(s)
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
    const s = line.trim();
    let m;
    if (!s) { close(); continue; }
    if ((m = s.match(/^#{1,6}\s+(.*)$/))) { close(); out.push(`<h3>${inline(heading(m[1]))}</h3>`); continue; }
    if ((m = s.match(/^[-*]\s+\[([ xX])\]\s+(.*)$/))) {
      if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; }
      out.push(`<li class="task${m[1] === " " ? "" : " done"}">${inline(m[2])}</li>`); continue;
    }
    if ((m = s.match(/^[-*]\s+(.*)$/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if ((m = s.match(/^\d+[.)]\s+(.*)$/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    close();
    out.push(`<p>${inline(s)}</p>`);
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
    if (h && h[1].trim().replace(/^"|"$/g, "").toLowerCase() === String(title).trim().toLowerCase()) lines.splice(first, 1);
  }
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
    if (!res.ok) throw Object.assign(new Error(srvText(data.code, data.params, data.error) || `HTTP ${res.status}`), { status: res.status });
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
    throw new Error(t("err.no_connection_nothing_saved"));
  }
  setOffline(false);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) throw new Error(srvText(data.code, data.params, data.error) || t("err.http", { status: res.status }));
  return data;
}
const okText = (res) => srvText(res.msg_code, res.msg_params, res.message) || t("common.saved");
function hhmm(d) { return d ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : "-"; }
function setOffline(off) {
  const bar = $("#offline");
  if (!off) {
    S.lastOk = new Date();
    if (S.offline) { S.offline = false; bar.hidden = true; document.body.classList.remove("is-offline"); }
    return;
  }
  if (!S.offline) S.offlineSince = new Date();
  S.offline = true;
  bar.textContent = t("err.offline_bar", { since: hhmm(S.offlineSince), data: hhmm(S.lastOk) });
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
  const tick = timer ? setInterval(() => { left -= 1000; const tm = $(".tmr", el); if (tm) tm.textContent = `${Math.max(0, Math.round(left / 1000))} s`; }, 1000) : null;
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
    toast(t("err.not_saved", { msg: err.message }), { error: true, action: () => closing(body, { label, restore, after }), actionLabel: t("common.retry"), ms: 9000 });
    return;
  }
  const id = res.pending.id;
  const undo = async () => {
    S.lastUndo = null;
    try {
      await post("/api/undo", { id });
      restore?.();
      toast(t("toast.undone", { what: label }));
    } catch (err) {
      toast(err.message, { error: true });
    }
  };
  S.lastUndo = { id, undo, until: Date.now() + UNDO_MS };
  const dismiss = toast(label, { action: undo, actionLabel: t("common.undo"), ms: UNDO_MS, timer: true });
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
        toast(t("err.not_saved", { msg: srvText(st.error_code, st.error_params, st.error) }), { error: true, action: () => closing(body, { label, restore, after }), actionLabel: t("common.retry"), ms: 10000 });
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
  today: { title: "nav.today", nav: "today", render: renderToday },
  decisions: { title: "nav.decisions", nav: "decisions", render: renderDecisions },
  projects: { title: "nav.projects", nav: "projects", render: renderProjects },
  tree: { title: "tree.title", nav: "tree", render: renderTree },
  activity: { title: "nav.activity", nav: "activity", render: renderActivity },
  tasks: { title: "nav.tasks", nav: "tasks", render: renderTasks },
};

function setTitle(title, sub = "") {
  $("#view-title").textContent = title;
  $("#view-sub").textContent = sub;
  const owner = S.meta?.owner_name;
  document.title = owner ? `${title} · ${owner}` : title;
}

async function route() {
  const prev = S.route;
  S.route = parseHash();
  const v = VIEWS[S.route.view] ? S.route.view : "today";
  const def = VIEWS[v];
  const sameView = prev.view === S.route.view && prev.rest === S.route.rest
    && JSON.stringify({ ...prev.q, task: "" }) === JSON.stringify({ ...S.route.q, task: "" });
  $$("[data-view]").forEach((a) => (a.dataset.view === def.nav ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  [...document.body.classList].filter((c) => c.startsWith("v-")).forEach((c) => document.body.classList.remove(c));
  document.body.classList.add(`v-${v}`);
  if (!sameView || !$("#main").dataset.ready) {
    if (S.tree && v !== "tree") { S.tree.destroy(); S.tree = null; document.body.classList.remove("tree-forced"); }
    setTitle(t(def.title), v === "today" && S.meta ? fmtDay(todayIso(), true) : "");
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
function errorBox(err) {
  main(`<section class="sec"><p class="empty">${esc(t("err.screen", { msg: err.message }))} <button class="link-btn" data-act="reload">${esc(t("common.try_again"))}</button></p></section>`);
}
const skeleton = (n = 8) => `<div class="skeleton" aria-hidden="true">${"<i></i>".repeat(n)}</div>`;
function navMore() {
  return `<nav class="nav-more" aria-label="${esc(t("a11y.more_nav"))}">
    <a href="#/tasks">${icon("list")}${esc(t("nav.tasks"))}</a><a href="#/tree">${icon("tree")}${esc(t("nav.tree"))}</a>
    <button type="button" class="btn-quiet" data-act="theme">${icon("theme")}${esc(themeLabel())}</button>
    <button type="button" class="btn-quiet" data-act="lang">${icon("lang")}${esc(t("lang.switch_to"))}</button></nav>`;
}

// ── rows ────────────────────────────────────────────────────────────────────
function row(s, opts = {}) {
  const d = dueInfo(s);
  const closed = s.status === "done" || s.status === "cancelled";
  const isDecision = s.type === "decision" && !closed;
  let mark;
  if (isDecision) mark = `<span class="mark dec" aria-hidden="true"></span>`;
  else if (closed) mark = s.status === "done" ? `<span class="mark ok" title="${esc(statusName("done"))}">${icon("check")}</span>` : `<span class="mark cx" title="${esc(statusName("cancelled"))}">${icon("close")}</span>`;
  else if (s.status === "blocked") mark = `<span class="mark blk" title="${esc(statusName("blocked"))}">${icon("block")}</span>`;
  else if (!s.human || opts.noCheck) mark = `<span class="mark agent" title="${esc(t("row.agent_task"))}">${icon(s.human ? "you" : "agent")}</span>`;
  else mark = `<button type="button" class="mark needs-net" data-act="check" data-key="${esc(s.key)}" aria-label="${esc(t("row.mark_done", { what: s.id || s.title }))}" title="${esc(t("row.mark_done_short"))}">${icon("check")}</button>`;
  const end = [];
  if (s.working) end.push(`<span class="chip-s agent keep"><span class="pulse"></span>${esc(t("row.working"))}</span>`);
  if (s.unblocks > 0) end.push(`<span class="unb" title="${esc(tn("row.unblocks_title", s.unblocks))}">${icon("agent")}${s.unblocks}</span>`);
  if (opts.state && (s.status === "in_progress" || s.status === "blocked")) end.push(`<span class="chip-s ${s.status === "blocked" ? "stop" : "agent"}">${esc(statusName(s.status))}</span>`);
  if (s.type === "review") end.push(`<span class="chip-s">${esc(t("row.review"))}</span>`);
  if (opts.kind) end.push(`<span class="kind ${opts.kind}">${icon(opts.kind === "you" ? "you" : opts.kind === "agent" ? "agent" : opts.kind === "decided" ? "decide" : "close")}${esc(t(`act.kind_${opts.kind}`))}</span>`);
  if (opts.when) end.push(`<span>${esc(fmtStamp(opts.when))}</span>`);
  else if (d.text) end.push(`<span class="due ${d.cls}">${esc(d.text)}</span>`);
  const projLabel = opts.showProject === false ? (s.human ? "" : who(s)) : projName(s) + (s.human || opts.side ? "" : ` · ${who(s)}`);
  const sub = opts.sub ? `<div class="sub">${opts.sub}</div>` : "";
  return `<li class="row${isDecision ? " decision" : ""}" data-key="${esc(s.key)}" tabindex="-1">
    ${mark}<span class="code">${esc(s.id || t("common.inbox_short"))}</span>
    <span class="ttl">${projLabel ? `<span class="proj">${esc(projLabel)}</span>` : ""}<a href="${esc(opts.href || (isDecision ? hashFor("decisions", s.key) : taskHref(s.key)))}">${esc(s.title)}</a></span>
    <span class="end">${end.join("")}</span>${sub}</li>`;
}
const rows = (list, opts) => `<ul class="rows">${list.map((s) => row(s, opts)).join("")}</ul>`;
const group = (label, list, cls, open, opts) => (list.length
  ? `<details class="group ${cls}" ${open ? "open" : ""}><summary>${icon("chev")}<span>${label}</span></summary>${rows(list, opts)}</details>` : "");

// ── Today ───────────────────────────────────────────────────────────────────
async function renderToday() {
  if (!S.today) main(skeleton(10));
  try { S.today = await api("/api/today"); } catch (e) { return errorBox(e); }
  const d = S.today;
  S.meta = { ...S.meta, ...d, language: S.meta?.language || d.language };
  updateCounts(d);
  setTitle(t("nav.today"), fmtDay(d.today, true));
  const m = d.mine;
  const dec = d.decisions;

  if (!d.projects && !dec.count && !m.today.length && !m.overdue.length && !m.week.length) {
    return main(`<section class="sec"><div class="stack-empty"><div><h2>${esc(t("today.no_project_title"))}</h2>
      <p>${t("today.no_project_body", { cmd: "<code>/new-project</code>" })}</p>
      <button class="btn" data-act="copy" data-text="/new-project">${esc(t("today.copy_command"))}</button></div></div></section>${navMore()}`);
  }

  const decSec = `<section class="sec decide-sec" aria-labelledby="h-dec">
      <div class="sec-head"><h2 id="h-dec">${esc(t("nav.decisions"))}</h2>
        <span class="meta">${dec.count ? `<b>${dec.count}</b> ${esc(tn("today.dec_waiting", dec.count, { n: "" }).trim())}${dec.overdue ? ` · <span class="stop">${esc(tn("today.dec_overdue", dec.overdue))}</span>` : ""}${dec.overdue && dec.on_time ? ` · ${esc(tn("today.dec_on_time", dec.on_time))}` : ""}` : ""}</span>
        ${dec.count ? `<a class="more hide-mobile" href="#/decisions">${esc(t("today.go_to_stack"))} ${icon("chev")}</a>` : ""}</div>
      ${dec.count ? `${rows(dec.top)}${dec.count > dec.top.length ? `<p class="hint hide-mobile">${esc(tn("today.more_in_stack", dec.count - dec.top.length))}</p>` : ""}
        <a class="btn stack-cta" href="${hashFor("decisions", dec.top[0].key)}">${esc(t("today.start_most_urgent", { n: dec.count }))}</a>`
    : `<p class="empty">${esc(t("today.no_decisions"))}<a href="#/activity">${esc(t("today.see_what_they_did"))}</a></p>`}
    </section>`;

  const mineSec = `<section class="sec" aria-labelledby="h-mine">
      <div class="sec-head"><h2 id="h-mine">${esc(t("today.your_tasks"))}</h2>
        <span class="meta">${esc(t("today.count_today"))} <b>${m.today.length}</b> · ${esc(t("today.count_overdue"))} <b class="${m.overdue.length ? "stop" : ""}">${m.overdue.length}</b> · ${esc(t("today.count_week"))} <b>${m.week.length}</b></span></div>
      ${m.today.length ? rows(m.today) : `<p class="empty">${esc(t("today.nothing_today"))}${m.overdue.length ? " " + esc(tn("today.overdue_below", m.overdue.length)) : ""}</p>`}
      ${m.week.length ? `<div class="subgroup">${esc(t("today.count_week"))} · ${m.week.length}</div>${rows(m.week)}` : ""}
      ${group(`${esc(t("today.count_overdue"))} <b>${m.overdue.length}</b>, ${esc(t("today.overdue_hint"))}`, m.overdue, "over", m.overdue.length <= 3 && !m.today.length)}
      ${group(`${esc(t("today.later"))}: ${m.later.length}`, m.later, "", false)}
    </section>`;

  const waitSec = `<section class="sec" aria-labelledby="h-wait">
      <div class="sec-head"><h2 id="h-wait">${esc(t("today.agents_waiting"))}</h2><span class="meta"><b>${d.waiting.length}</b> ${esc(tn("today.blocks", d.waiting.length, { n: "" }).trim())}</span></div>
      ${d.waiting.length ? `<ul class="rows">${d.waiting.map((s) => row(s, { side: true,
        sub: `${s.unblocking_action ? `<b>${esc(t("today.needs"))}</b> ${inlineMd(s.unblocking_action.replace(/\s+/g, " ").slice(0, 200))}` : esc(t("today.waits_on", { id: s.unblocked_by || (s.blocked_by || []).join(", ") }))}` })).join("")}</ul>`
    : `<p class="empty">${esc(t("today.no_waiting"))}</p>`}
    </section>`;

  const reviewSec = d.review.length ? `<section class="sec" aria-labelledby="h-rev">
      <div class="sec-head"><h2 id="h-rev">${esc(t("today.review"))}</h2><span class="meta"><b>${d.review.length}</b></span></div>
      ${rows(d.review, { side: true })}</section>` : "";

  const stat = `<p class="statline"><span>${d.agents_working ? `<span class="pulse"></span>${esc(tn("today.agents_working", d.agents_working))}` : esc(t("today.no_agent_working"))}</span>
    <span>${esc(tn("today.closed_24h", d.closed_24h))} · <a href="#/activity">${esc(t("nav.activity"))}</a></span></p>`;

  main(`<div class="today-grid"><div class="col-main">${decSec}${mineSec}</div><div class="col-side">${waitSec}${reviewSec}${stat}</div></div>${errorsNote(d.errors)}${navMore()}`);
}
function errorsNote(errors) {
  if (!errors || !errors.length) return "";
  return `<details class="notice"><summary>${esc(tn("err.skipped_files", errors.length))}</summary><ul>${errors.map((e) => `<li><code>${esc(e)}</code></li>`).join("")}</ul></details>`;
}

// ── Decisions (stack) ───────────────────────────────────────────────────────
function stackList() {
  let l = S.decisions.items;
  if (S.stackFilter === "overdue") l = l.filter((s) => s.overdue_days > 0);
  if (S.stackGroup === "project") {
    l = l.slice().sort((a, b) => projName(a).localeCompare(projName(b), locale()) || (a.due || "9999").localeCompare(b.due || "9999"));
  }
  return l;
}
async function renderDecisions() {
  if (!S.decisions) main(skeleton(12));
  try { S.decisions = await api("/api/decisions"); } catch (e) { return errorBox(e); }
  const list = stackList();
  const want = S.route.rest;
  const i = want ? list.findIndex((s) => s.key === want) : -1;
  S.decIdx = i >= 0 ? i : Math.min(S.decIdx, Math.max(0, list.length - 1));
  drawStack();
}
function drawStack(tick = false) {
  S.armed = null;
  const all = S.decisions.items;
  const n = all.length;
  const over = all.filter((s) => s.overdue_days > 0).length;
  setTitle(t("nav.decisions"), n ? `${tn("today.dec_waiting", n)}${over ? `, ${tn("today.dec_overdue", over)}` : ""}` : "");
  $$('[data-count="decisions"]').forEach((el) => { el.textContent = n || ""; });
  const list = stackList();
  if (!list.length) {
    return main(`<div class="stack"><div class="stack-empty"><div>
      <h2>${esc(t(n ? "dec.none_overdue" : "dec.none_title"))}</h2>
      <p>${esc(n ? tn("dec.on_time_in_stack", n) : t("dec.none_body"))}</p>
      <p>${n ? `<button type="button" class="btn" data-act="stack-all">${esc(t("dec.show_all"))}</button>` : `<a class="btn" href="#/activity">${esc(t("today.see_what_they_did"))}</a>`}</p></div></div></div>`);
  }
  S.decIdx = Math.min(S.decIdx, list.length - 1);
  const cur = list[S.decIdx];
  let lastGroup = null;
  const items = list.map((s, i) => {
    let head = "";
    if (S.stackGroup === "project" && projName(s) !== lastGroup) { lastGroup = projName(s); head = `<li class="grp">${esc(lastGroup)}</li>`; }
    const di = dueInfo(s);
    return `${head}<li class="si" data-act="pick" data-i="${i}" ${i === S.decIdx ? 'aria-current="true"' : ""} tabindex="-1">
      <span class="dot ${di.cls === "over" ? "over" : ""}"></span><span class="t">${esc(s.title)}</span>
      <span class="d ${di.cls === "over" ? "over" : ""}">${esc(di.text)}</span>
      <span class="m">${esc(s.id)} · ${esc(projName(s))}</span></li>`;
  }).join("");
  const d = dueInfo(cur);
  const links = (cur.links || []).map((l) => /^https?:/i.test(l.href)
    ? `<a class="chip-s" href="${esc(l.href)}" target="_blank" rel="noopener noreferrer">${esc(l.label)}</a>`
    : `<span class="chip-s" title="${esc(l.href)}">${esc(l.label)}</span>`).join("");
  const countChanged = tick && S.prevCount !== null && S.prevCount !== n;
  S.prevCount = n;
  main(`<div class="stack" id="stack">
    <aside class="stack-list" aria-label="${esc(t("dec.list_label"))}">
      <div class="stack-list-head"><span class="stack-count${countChanged ? " tick" : ""}" aria-live="polite">${n}</span>
        <span class="stack-count-label">${esc(tn("dec.count_label", n, { n: "" }).trim())}<br>${esc(over ? tn("today.dec_overdue", over) : t("dec.all_on_time"))}</span>
        <div class="stack-filters">
          <button type="button" class="chip" data-act="stack-filter" aria-pressed="${S.stackFilter === "overdue"}">${esc(t("dec.filter_overdue"))}</button>
          <button type="button" class="chip" data-act="stack-group" aria-pressed="${S.stackGroup === "project"}">${esc(t("dec.group_project"))}</button>
        </div></div>
      <ul class="stack-items">${items}</ul>
    </aside>
    <article class="stack-detail" aria-labelledby="slip-title" data-key="${esc(cur.key)}">
      <div class="stack-detail-head">
        <button type="button" class="btn btn-stack-list" data-act="stack-toggle">${icon("decide")}${esc(t("dec.list_button", { n }))}</button>
        <span class="code">${esc(cur.id)}</span><span>${esc(projName(cur))}</span>
        ${cur.due ? `<span class="due ${d.cls}">${esc(t("dec.due_by", { date: fmtDay(cur.due) }))}${d.cls === "over" ? ` · ${esc(d.text)}` : ""}</span>` : ""}
        <span class="pos">${S.decIdx + 1} / ${list.length}</span></div>
      <div class="stack-body">
        <h2 class="dec-title" id="slip-title">${esc(cur.title)}</h2>
        <div class="rec"><div class="rec-label">${esc(t("dec.recommendation"))}</div>${cur.recommendation ? md(cur.recommendation) : `<p class="muted">${esc(t("dec.no_recommendation"))}</p>`}</div>
        ${cur.context ? `<div class="rec-label quiet">${esc(t("hdr.context"))}</div>${md(cur.context)}` : ""}
        ${links ? `<div class="links">${links}</div>` : ""}
        ${cur.notes ? `<div class="rec-label quiet">${esc(t("dec.earlier_notes"))}</div>${md(cur.notes)}` : ""}
        <details class="full" data-key="${esc(cur.key)}"><summary>${esc(t("dec.full_task"))}</summary><div class="full-body muted">${esc(t("common.loading"))}</div></details>
      </div>
      <div class="stack-foot">
        <textarea id="dec-note" rows="2" placeholder="${esc(t("dec.comment_placeholder"))}" aria-label="${esc(t("dec.comment_label"))}"></textarea>
        <div class="row-btns">
          <button type="button" class="btn-ok needs-net" data-act="decide" data-v="accept"><kbd>A</kbd><span class="lbl">${esc(t("dec.accept"))}</span></button>
          <button type="button" class="btn-stop needs-net" data-act="decide" data-v="reject"><kbd>O</kbd><span class="lbl">${esc(t("dec.reject"))}</span></button>
          <button type="button" class="btn-quiet" data-act="skip"><kbd>S</kbd>${esc(t("dec.skip"))}</button>
          <span class="nav-keys"><button type="button" class="icon-btn" data-act="prev" aria-label="${esc(t("dec.prev"))}" title="${esc(t("dec.prev"))} (K)">${icon("back")}</button>
          <button type="button" class="icon-btn" data-act="next" aria-label="${esc(t("dec.next"))}" title="${esc(t("dec.next"))} (J)">${icon("arrow")}</button></span>
        </div>
      </div>
    </article></div>`);
  const curEl = $(".stack-items [aria-current]"); if (curEl) curEl.scrollIntoView({ block: "nearest" });
  const want = hashFor("decisions", cur.key);
  if (location.hash !== want && !S.route.q.task) history.replaceState(null, "", want);
  S.route = parseHash();
}
function moveDecision(delta) {
  const n = S.decisions ? stackList().length : 0;
  if (!n) return;
  S.decIdx = (S.decIdx + delta + n) % n;
  drawStack();
}
const decLabel = (kind) => t(kind === "accept" ? "dec.accept" : "dec.reject");
function armOrCommit(kind) {
  const btn = $(`[data-act="decide"][data-v="${kind}"]`);
  if (!btn || S.offline) return;
  if (S.armed && S.armed.kind === kind && Date.now() < S.armed.until) return commitDecision(kind);
  $$('[data-act="decide"]').forEach((b) => { b.classList.remove("armed"); $(".lbl", b).textContent = decLabel(b.dataset.v); });
  S.armed = { kind, until: Date.now() + ARM_MS };
  btn.classList.add("armed");
  $(".lbl", btn).textContent = t(kind === "accept" ? "dec.confirm_accept" : "dec.confirm_reject");
  setTimeout(() => {
    if (S.armed && S.armed.kind === kind && Date.now() >= S.armed.until) {
      S.armed = null; btn.classList.remove("armed");
      const l = $(".lbl", btn); if (l) l.textContent = decLabel(kind);
    }
  }, ARM_MS + 50);
}
function commitDecision(kind) {
  const list = stackList();
  const cur = list[S.decIdx];
  if (!cur) return;
  const note = ($("#dec-note")?.value || "").trim();
  const all = S.decisions.items;
  const at = all.indexOf(cur);
  all.splice(at, 1);
  S.decisions.count = all.length;
  if (S.decIdx >= stackList().length) S.decIdx = Math.max(0, stackList().length - 1);
  drawStack(true);
  const accepted = kind === "accept";
  closing({ action: "decide", key: cur.key, accepted, note }, {
    label: t(accepted ? "toast.accepted" : "toast.rejected", { id: cur.id }),
    restore: () => {
      if (S.route.view !== "decisions") return;
      if (!S.decisions.items.some((s) => s.key === cur.key)) S.decisions.items.splice(Math.min(at, S.decisions.items.length), 0, cur);
      S.decIdx = Math.max(0, stackList().indexOf(cur));
      drawStack(true);
      const ta = $("#dec-note"); if (ta) ta.value = note;
    },
  });
}

// ── Projects ────────────────────────────────────────────────────────────────
function healthDots(h) {
  const label = t(`proj.health_${h}`);
  return `<span class="health h${h}" title="${esc(label)}: ${esc(t("proj.health_rule"))}" role="img" aria-label="${esc(label)}"><i></i><i></i><i></i></span>`;
}
function wipHtml(p) {
  const pct = Math.min(100, Math.round((100 * p.wip) / Math.max(1, p.wip_limit)));
  return `<span class="wip" title="${esc(t("proj.wip_title"))}">${p.wip}/${p.wip_limit}<span class="wip-bar${p.wip > p.wip_limit ? " over" : ""}"><i data-w="${pct}"></i></span></span>`;
}
const zero = (n, cls = "") => (n ? `<span class="${cls}">${n}</span>` : `<span class="zero">0</span>`);
async function renderProjects() {
  if (S.route.rest) return renderProject(S.route.rest);
  if (!S.projects) main(skeleton(10));
  try { S.projects = await api("/api/projects"); } catch (e) { return errorBox(e); }
  const items = S.projects.items;
  setTitle(t("nav.projects"), tn("proj.count", items.length));
  if (!items.length) {
    return main(`<section class="sec"><div class="stack-empty"><div><h2>${esc(t("today.no_project_title"))}</h2><p>${t("today.no_project_body", { cmd: "<code>/new-project</code>" })}</p>
      <button class="btn" data-act="copy" data-text="/new-project">${esc(t("today.copy_command"))}</button></div></div></section>${navMore()}`);
  }
  const table = `<table class="grid"><thead><tr><th>${esc(t("proj.col_project"))}</th><th>${esc(t("proj.col_health"))}</th><th class="r">${esc(t("proj.col_open"))}</th><th class="r">${esc(t("proj.col_yours"))}</th><th class="r">${esc(t("proj.col_decisions"))}</th><th class="r">${esc(t("proj.col_blocked"))}</th><th class="r">${esc(t("proj.col_overdue"))}</th><th>WIP</th><th class="c-move">${esc(t("proj.col_last_move"))}</th></tr></thead><tbody>
    ${items.map((p) => `<tr data-href="#/projects/${esc(p.slug)}"><td class="name"><a href="#/projects/${esc(p.slug)}">${esc(p.name)}</a>${p.status !== "active" ? ` <span class="chip-s">${esc(t(`proj.status_${p.status}`))}</span>` : ""}<small title="${esc(p.phase || "")}">${esc(p.phase || p.last_title || "")}</small></td>
      <td>${healthDots(p.health)}</td><td class="r">${zero(p.open)}</td><td class="r">${zero(p.yours)}</td><td class="r">${zero(p.decisions)}</td>
      <td class="r">${zero(p.blocked, "stop")}</td><td class="r">${zero(p.overdue, "stop")}</td><td>${wipHtml(p)}</td>
      <td class="c-move">${esc(fmtStamp(p.last_move))} <span class="who">${esc(p.last_owner ? roleName(p.last_owner === "human" ? "" : p.last_owner) : "")}</span></td></tr>`).join("")}
    </tbody></table>`;
  const cards = `<ul class="pcards">${items.map((p) => `<li data-href="#/projects/${esc(p.slug)}"><a href="#/projects/${esc(p.slug)}">
      <div class="n">${esc(p.name)} ${healthDots(p.health)}</div>
      <div class="m">${esc(tn("proj.card_open", p.open))} · ${esc(t("proj.col_yours"))} ${p.yours}${p.decisions ? ` · ${esc(t("proj.col_decisions").toLowerCase())} ${p.decisions}` : ""}${p.blocked ? ` · <span class="stop">${esc(t("proj.col_blocked").toLowerCase())} ${p.blocked}</span>` : ""}${p.overdue ? ` · <span class="stop">${esc(tn("proj.card_overdue", p.overdue))}</span>` : ""}</div></a></li>`).join("")}</ul>`;
  main(`<section class="sec"><div class="sec-head"><h2>${esc(t("proj.health_heading"))}</h2><span class="meta">${esc(t("proj.health_sub"))}</span>
      <a class="more" href="#/tree">${icon("tree")}${esc(t("proj.tree_link"))}</a></div>
    <div class="table-wrap">${table}${cards}</div>
    ${S.projects.inbox_open ? `<p class="hint">${esc(tn("proj.inbox_open", S.projects.inbox_open))} · <a href="#/tasks">${esc(t("nav.tasks"))}</a></p>` : ""}</section>${navMore()}`);
}

function depNode(n) {
  const kids = n.children || [];
  const cls = [n.human ? "human" : "", n.status === "blocked" ? "blocked" : ""].join(" ");
  const d = dueInfo(n);
  const lead = n.type === "decision" ? '<span class="dot-d"></span>' : n.working ? '<span class="pulse"></span>' : n.human ? icon("you") : icon("agent");
  const extra = n.ref ? ` <span class="muted">${esc(t("deps.shown_above"))}</span>` : n.cycle ? ` <span class="chip-s stop">${esc(t("deps.cycle"))}</span>` : "";
  return `<li><div class="dnode">${kids.length ? `<button type="button" class="tog" data-act="tog" aria-expanded="true" aria-label="${esc(t("deps.collapse", { id: n.id }))}"></button>` : '<span class="spacer"></span>'}
      <a class="tk ${cls}" href="${esc(taskHref(n.key))}">${lead}<span class="mono">${esc(n.id)}</span><span class="t">${esc(n.title)}</span></a>${extra}
      <span class="who">${esc(who(n))}${d.text ? ` · <span class="due ${d.cls}">${esc(d.text)}</span>` : ""}</span></div>
    ${kids.length ? `<ul>${kids.map(depNode).join("")}</ul>` : ""}</li>`;
}
function depsBlock(tree) {
  const chains = tree.chains.length ? `<ul class="deps" aria-label="${esc(t("deps.title"))}">${tree.chains.map(depNode).join("")}</ul>` : `<p class="empty">${esc(t("deps.none"))}</p>`;
  const lanes = tree.lanes.length ? `<div class="lanes">${tree.lanes.map((l) => `<div class="lane"><h4>${esc(t("deps.not_linked", { who: l.lane === "you" ? t("role.you") : roleName(l.lane) }))}</h4><div class="tk-wrap">
      ${l.tasks.map((n) => `<a class="${n.overdue_days ? "stop" : n.type === "decision" ? "decide" : ""}" href="${esc(taskHref(n.key))}" title="${esc(n.title)}"><span class="mono">${esc(n.id)}</span> ${esc(n.title)}</a>`).join("")}</div></div>`).join("")}</div>` : "";
  return chains + lanes + `<p class="hint">${esc(t("deps.legend"))}</p>`;
}

async function renderProject(slug) {
  if (!S.project || S.project.slug !== slug) main(skeleton(10));
  try { S.project = await api(`/api/project/${encodeURIComponent(slug)}`); } catch (e) {
    return main(`<section class="sec"><p class="empty">${esc(e.status === 404 ? t("proj.missing") : t("err.screen", { msg: e.message }))} <a href="#/projects">${esc(t("proj.all"))}</a></p></section>`);
  }
  const p = S.project;
  setTitle(p.name, p.status !== "active" ? t(`proj.status_${p.status}`) : "");
  const ph = p.phase.current;
  const phase = ph ? `${/^(phase|stage|faza|etap)/i.test(ph.title) ? "" : esc(t("proj.phase")) + ": "}${esc(ph.title)} · ${esc(t("proj.phase_done", { done: ph.done, total: ph.done + ph.open }))}` : esc(t("proj.no_phases"));
  const num = (v, label, cls) => `<div class="pnum ${cls || ""}"><b>${v}</b>${esc(label)}</div>`;
  const overdue = [...p.yours, ...p.agents, ...p.decisions].filter((s) => s.overdue_days > 0).length;
  const blockers = p.blockers.map((s) => `<div class="block-card"><div class="t"><a href="${esc(taskHref(s.key))}"><span class="mono">${esc(s.id)}</span> ${esc(s.title)}</a></div>
      <div class="m">${esc(who(s))}${s.unblocked_by ? ` · ${esc(t("today.waits_on", { id: s.unblocked_by }))}` : (s.blocked_by || []).length ? ` · ${esc(t("today.waits_on", { id: s.blocked_by.join(", ") }))}` : ""}</div>
      ${s.unblocking_action ? md(s.unblocking_action) : `<p class="hint">${esc(t("proj.no_unblocking"))}</p>`}
      ${s.unblocked_by_key ? `<p><a class="btn" href="${esc(taskHref(s.unblocked_by_key))}">${esc(t("today.open_id", { id: s.unblocked_by }))}</a></p>` : ""}</div>`).join("");
  const list = (title, items, opts, empty) => `<section class="sec"><div class="sec-head"><h2>${esc(title)}</h2><span class="meta"><b>${items.length}</b></span></div>${items.length ? rows(items, opts) : `<p class="empty">${esc(empty)}</p>`}</section>`;
  main(`<a class="back" href="#/projects">${icon("back")}${esc(t("proj.all"))}</a>
    <div class="phead"><div><h2>${esc(p.name)}</h2><div class="phase">${phase}</div>
        ${p.goal ? `<div class="goal">${md(p.goal)}</div>` : ""}
        ${p.success ? `<details><summary>${esc(t("hdr.success"))}</summary>${md(p.success)}</details>` : ""}</div>
      <div class="pnums">${num(`${p.wip}/${p.wip_limit}`, "WIP", p.wip > p.wip_limit ? "stop" : "")}${num(p.blockers.length, t("proj.n_blocked"), p.blockers.length ? "stop" : "")}${num(overdue, t("proj.n_overdue"), overdue ? "stop" : "")}${num(p.decisions.length, t("proj.n_decisions"))}</div></div>
    ${p.blockers.length ? `<section class="sec"><div class="sec-head"><h2>${esc(t("proj.blocked"))}</h2><span class="meta">${esc(t("proj.blocked_sub"))}</span></div>${blockers}</section>` : ""}
    ${p.decisions.length ? list(t("nav.decisions"), p.decisions, { showProject: false }, "") : ""}
    <div class="two-col">
      ${list(t("today.your_tasks"), p.yours, { showProject: false }, t("proj.nothing_yours"))}
      ${list(t("proj.agent_tasks"), p.agents, { showProject: false, state: true }, t("proj.no_agent_tasks"))}
    </div>
    <section class="sec"><div class="sec-head"><h2>${esc(t("deps.title"))}</h2><span class="meta">${esc(t("deps.linked", { linked: p.tree.linked, open: p.tree.open }))}</span>
      <a class="more" href="#/tree">${icon("tree")}${esc(t("proj.tree_link"))}</a></div>${depsBlock(p.tree)}</section>
    <section class="sec"><div class="sec-head"><h2>${esc(t("proj.recent_log"))}</h2></div>${p.log.length ? p.log.map((l) => `<div class="log-item"><time>${esc(fmtStamp((l.when || "").replace(" ", "T")))}</time><div>${md(l.text)}</div></div>`).join("") : `<p class="empty">${esc(t("proj.log_empty"))}</p>`}</section>
    ${p.recent_closed.length ? `<section class="sec">${group(`${esc(t("proj.closed_7d"))}: ${p.recent_closed.length}`, p.recent_closed, "", false, { showProject: false })}</section>` : ""}`);
}

// ── Tree (organisation) ─────────────────────────────────────────────────────
async function renderTree() {
  setTitle(t("tree.title"), "");
  if (S.tree) { S.tree.destroy(); S.tree = null; }
  S.tree = mountTree($("#main"), {
    t, tn, api,
    ownerName: () => S.meta?.owner_name || t("role.you"),
    roleName: (r) => (r === "human" ? (S.meta?.owner_name || t("role.you")) : roleName(r)),
    statusName, prioName, fmtDay, fmtStamp,
    openTask: (n) => go(n.decision ? hashFor("decisions", n.key) : hashFor("tree", "", { task: n.key })),
    setSub: (txt) => { $("#view-sub").textContent = txt; },
    onForce: () => document.body.classList.add("tree-forced"),
  });
}

// ── Activity ────────────────────────────────────────────────────────────────
function markVisit() {
  // "since your last visit": remember the previous visit, refresh the current one later
  if (S.visitMarked) return;
  S.visitMarked = true;
  setTimeout(() => ls.set(LS.visit, localIso()), 10000);
}
async function renderActivity() {
  const range = S.route.q.range || (S.lastVisit ? "visit" : "24h");
  const now = new Date();
  let since = "";
  if (range === "visit" && S.lastVisit) since = S.lastVisit;
  else if (range === "7d") since = localIso(new Date(now - 7 * 86400000));
  else if (range === "all") since = "2000-01-01T00:00";
  else since = localIso(new Date(now - 86400000));
  if (!S.activity) main(skeleton(8));
  try { S.activity = await api(`/api/activity?since=${encodeURIComponent(since)}${range === "all" ? "&archive=1" : ""}`); } catch (e) { return errorBox(e); }
  const a = S.activity;
  setTitle(t("nav.activity"), tn("act.closures", a.total));
  const tab = (r, label) => `<a href="${hashFor("activity", "", { range: r })}" ${r === range ? 'aria-current="page"' : ""}>${esc(label)}</a>`;
  const heading = range === "visit" ? t("act.since_visit", { when: fmtStamp(S.lastVisit) })
    : range === "7d" ? t("act.last_7d") : range === "all" ? t("act.everything") : t("act.last_24h");
  let agents = 0; let you = 0; let cancelled = 0;
  const groups = a.groups.map((g) => {
    const c = { agent: 0, you: 0, cancelled: 0 };
    g.items.forEach((s) => { if (s.kind === "agent") c.agent += 1; else if (s.kind === "cancelled") c.cancelled += 1; else c.you += 1; });
    agents += c.agent; you += c.you; cancelled += c.cancelled;
    return { ...g, c };
  });
  const max = Math.max(1, ...groups.map((g) => g.items.length));
  const body = groups.map((g, gi) => {
    const nItems = g.items.length;
    return `<details class="act-row" ${gi < 2 ? "open" : ""}><summary>
      <span><b>${esc(g.name || t("common.inbox"))}</b></span><span class="n">${nItems}</span>
      <span class="act-bar-track"><span class="act-bar" data-w="${Math.max(6, Math.round((100 * nItems) / max))}"><i class="a" data-w="${(100 * g.c.agent) / nItems}"></i><i class="y" data-w="${(100 * g.c.you) / nItems}"></i><i class="x" data-w="${(100 * g.c.cancelled) / nItems}"></i></span></span>
      <span class="op">${esc(t("act.split", { agents: g.c.agent, you: g.c.you }))}${g.c.cancelled ? ` · ${esc(tn("act.cancelled_n", g.c.cancelled))}` : ""}</span></summary>
      <ul class="rows">${g.items.map((s) => row(s, { showProject: false, noCheck: true, when: s.when, kind: s.kind })).join("")}</ul></details>`;
  }).join("");
  main(`<div class="toolbar"><nav class="range" aria-label="${esc(t("act.range_label"))}">${S.lastVisit ? tab("visit", t("act.tab_visit")) : ""}${tab("24h", t("act.tab_24h"))}${tab("7d", t("act.tab_7d"))}${tab("all", t("act.tab_all"))}</nav></div>
    <p class="act-sum">${esc(heading)}: <b>${a.total}</b> ${esc(tn("act.closures", a.total, { n: "" }).trim())}. ${esc(t("act.summary", { agents, you, cancelled }))}
      ${esc(t("act.your_decisions", { accepted: a.accepted, rejected: a.rejected }))}${a.clamped ? ` ${esc(t("act.clamped"))}` : ""}</p>
    <div class="legend"><span><i class="lg-agent"></i>${esc(t("act.legend_agents"))}</span><span><i class="lg-you"></i>${esc(t("act.legend_you"))}</span><span><i class="lg-cx"></i>${esc(t("act.legend_cancelled"))}</span></div>
    <section class="sec">${body || `<p class="empty">${esc(t("act.nothing"))} <a href="${hashFor("activity", "", { range: "7d" })}">${esc(t("act.look_7d"))}</a></p>`}</section>
    ${a.working.length ? `<section class="sec">${group(`${esc(t("act.working_now"))} <b>${a.working.length}</b>`, a.working, "", false, { state: true })}</section>` : ""}${navMore()}`);
}

// ── All tasks ───────────────────────────────────────────────────────────────
async function renderTasks() {
  const q = S.route.q;
  const scope = ["open", "recent", "all"].includes(q.scope) ? q.scope : "open";
  const whoF = ["mine", "agents"].includes(q.who) ? q.who : "all";
  if (!S.tasks) main(skeleton(10));
  try { S.tasks = await api(`/api/tasks?scope=${scope}`); } catch (e) { return errorBox(e); }
  const needle = (q.q || "").toLowerCase();
  let items = S.tasks.items.filter((s) => (whoF === "all" || (whoF === "mine") === s.human));
  if (needle) items = items.filter((s) => `${s.id} ${s.title} ${s.project_name} ${s.owner}`.toLowerCase().includes(needle));
  const shown = items.slice(0, 400);
  const tab = (k, v, label, cur) => `<a href="${hashFor("tasks", "", { ...q, [k]: v, task: "" })}" ${cur === v ? 'aria-current="page"' : ""}>${esc(label)}</a>`;
  $("#search").value = q.q || "";
  setTitle(t("nav.tasks"), tn("tasks.count", items.length));
  main(`<div class="toolbar">
      <nav class="range" aria-label="${esc(t("tasks.whose"))}">${tab("who", "all", t("tasks.everyone"), whoF)}${tab("who", "mine", t("tasks.mine"), whoF)}${tab("who", "agents", t("tasks.agents"), whoF)}</nav>
      <nav class="range" aria-label="${esc(t("tasks.which"))}">${tab("scope", "open", t("tasks.open"), scope)}${tab("scope", "recent", t("tasks.recent"), scope)}${tab("scope", "all", t("tasks.archive"), scope)}</nav>
      ${needle ? `<span class="muted">${esc(t("tasks.matching", { q: q.q }))}</span>` : ""}</div>
    <section class="sec">${shown.length ? rows(shown, { state: true }) : `<p class="empty">${esc(t("tasks.none"))}</p>`}
      ${items.length > shown.length ? `<p class="hint">${esc(t("tasks.first_n", { n: shown.length }))}</p>` : ""}</section>${navMore()}`);
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
  dr.innerHTML = `<div class="dr-head"><span>${esc(t("common.loading"))}</span><button class="icon-btn x" data-close="drawer" aria-label="${esc(t("common.close"))}">${icon("close")}</button></div>`;
  try {
    S.drawer = await api(`/api/task/${key.split("/").map(encodeURIComponent).join("/")}`);
  } catch (e) {
    dr.innerHTML = `<div class="dr-head"><span>${esc(e.status === 404 ? t("drawer.gone") : e.message)}</span><button class="icon-btn x" data-close="drawer" aria-label="${esc(t("common.close"))}">${icon("close")}</button></div>`;
    return;
  }
  drawDrawer();
  dr.focus();
}
function drawDrawer() {
  const s = S.drawer;
  const dr = $("#drawer");
  const d = dueInfo(s);
  const closed = ["done", "cancelled"].includes(s.status);
  const isDecision = s.type === "decision";
  const statusChip = s.status === "blocked" ? "stop" : s.status === "done" ? "ok" : s.working || s.status === "in_progress" ? "agent" : isDecision ? "decide" : "";
  const refLink = (id) => {
    const k = `${s.project}/${id}`;
    return s.project ? `<a href="${esc(hashFor(S.route.view, S.route.rest, { ...S.route.q, task: k }))}" class="mono">${esc(id)}</a>` : esc(id);
  };
  const waits = [...new Set([...(s.blocked_by || []), ...(s.unblocked_by ? [s.unblocked_by] : [])])];
  const evidence = s.evidence ? (/^https?:\/\//i.test(s.evidence) ? `<a href="${esc(s.evidence)}" target="_blank" rel="noopener noreferrer">${esc(s.evidence)}</a>`
    : /[\\/]/.test(s.evidence) && !/\s/.test(s.evidence) ? `<code>${esc(s.evidence)}</code>` : esc(s.evidence)) : "";
  const A = s.actions;
  let foot = "";
  if (s.archived) foot = `<p class="reason">${esc(t("drawer.archived"))}</p>`;
  else if (!S.editing) {
    const primary = isDecision && A.decide
      ? `<button class="btn-ok needs-net" data-act="d-decide" data-v="accept"><span class="lbl">${esc(t("dec.accept"))}</span></button><button class="btn-stop needs-net" data-act="d-decide" data-v="reject"><span class="lbl">${esc(t("dec.reject"))}</span></button>`
      : A.done ? `<button class="btn-ok needs-net" data-act="d-done">${icon("check")}<span class="lbl">${esc(t("drawer.mark_done"))}</span></button>` : "";
    foot = `<div class="dr-done" hidden><label class="field"><span>${esc(t("drawer.evidence_label"))}</span><input id="d-evidence" autocomplete="off" value="${esc(s.evidence)}" placeholder="${esc(t("drawer.evidence_placeholder"))}"></label></div>
      <label class="lbl" for="d-note">${esc(t("drawer.comment_label"))}</label><textarea id="d-note" rows="2" placeholder="${esc(t("drawer.comment_placeholder"))}"></textarea>
      <div class="dr-acts">${primary}
        <button class="btn needs-net" data-act="d-note">${esc(t("drawer.add_note"))}</button>
        ${A.cancel ? `<button class="btn-stop needs-net" data-act="d-cancel">${esc(t(S.closingAsk ? "drawer.confirm_cancel" : "drawer.cancel_task"))}</button>` : ""}
        <span class="sp"></span>
        ${A.edit ? `<button class="btn-quiet" data-act="d-edit">${esc(t("drawer.edit"))}</button>` : ""}
        ${A.run_now ? `<button class="btn needs-net" data-act="d-run">${icon("play")}${esc(t("drawer.run_now"))}</button>` : ""}
      </div>`;
  }
  const runReason = srvText(s.run_now_code, s.run_now_params, s.run_now_reason);
  const body = S.editing ? `<form class="edit" id="edit-form">
      <label class="field"><span>${esc(t("drawer.f_title"))}</span><input name="title" value="${esc(s.title)}" maxlength="200" required></label>
      <div class="row-fields"><label class="field"><span>${esc(t("new.priority"))}</span><select name="priority">${["high", "normal", "low"].map((p) => `<option value="${p}" ${p === s.priority ? "selected" : ""}>${esc(prioName(p))}</option>`).join("")}</select></label>
        <label class="field"><span>${esc(t("new.due"))}</span><input type="date" name="due" value="${esc(s.due)}"></label></div>
      <label class="field"><span>${esc(t("drawer.f_body"))}</span><textarea name="body">${esc(s.body.replace(/^\n+/, ""))}</textarea></label>
      <div class="dr-acts"><button type="submit" class="btn-primary needs-net">${esc(t("common.save"))}</button><button type="button" class="btn-quiet" data-act="d-edit-cancel">${esc(t("drawer.discard"))}</button></div>
    </form>` : `
      <dl class="facts">
        <dt>${esc(t("drawer.owner"))}</dt><dd>${esc(s.human ? (S.meta?.owner_name || t("role.you")) : who(s))}${s.autonomy === "ask" ? ` <span class="chip-s">${esc(t("drawer.asks_first"))}</span>` : ""}</dd>
        <dt>${esc(t("drawer.status"))}</dt><dd>${esc(statusName(s.status))}</dd>
        ${s.due ? `<dt>${esc(t("new.due"))}</dt><dd><span class="due ${d.cls}">${esc(fmtDate(s.due))}${d.cls === "over" ? " · " + esc(d.text) : ""}</span></dd>` : ""}
        <dt>${esc(t("new.priority"))}</dt><dd>${esc(prioName(s.priority))}</dd>
        ${waits.length ? `<dt>${esc(t("drawer.waits_on"))}</dt><dd>${waits.map(refLink).join(", ")}</dd>` : ""}
        ${s.waiting_on_this.length ? `<dt>${esc(t("drawer.unblocks"))}</dt><dd>${s.waiting_on_this.map((k) => refLink(k.split("/")[1])).join(", ")}</dd>` : ""}
        ${evidence ? `<dt>${esc(t("drawer.evidence"))}</dt><dd>${evidence}</dd>` : ""}
        ${s.decision ? `<dt>${esc(t("drawer.decision"))}</dt><dd><span class="chip-s ${s.decision === "accepted" ? "ok" : "stop"}">${esc(decisionName(s.decision))}</span></dd>` : ""}
        <dt>${esc(t("drawer.file"))}</dt><dd><code>${esc(s.rel_path)}</code></dd>
      </dl>
      ${!s.archived && !A.run_now && !s.human && !isDecision && s.status === "todo" && runReason ? `<p class="reason">${esc(t("drawer.run_unavailable", { reason: runReason }))}</p>` : ""}
      ${md(cleanBody(s.body, s.title))}`;
  dr.innerHTML = `<div class="dr-head"><span class="chip-s ${statusChip}">${esc(isDecision ? t("row.decision") : s.type === "review" ? t("row.review") : statusName(s.status))}</span>
      <span class="mono">${esc(s.id || t("common.inbox_short"))}</span><span class="pn">${esc(projName(s))}</span>${d.cls === "over" && !closed ? `<span class="over">${esc(d.text)}</span>` : ""}${s.working ? `<span class="chip-s agent"><span class="pulse"></span>${esc(t("row.working"))}</span>` : ""}
      <button class="icon-btn x" data-close="drawer" aria-label="${esc(t("common.close"))}">${icon("close")}</button></div>
    <h2 id="drawer-title">${esc(s.title)}</h2>
    <div class="dr-body">${body}</div>
    ${foot ? `<div class="dr-foot">${foot}</div>` : ""}`;
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
  const s = S.drawer;
  if (!s) return;
  const note = ($("#d-note")?.value || "").trim();
  if (kind === "note") {
    if (!note) { $("#d-note").focus(); return toast(t("drawer.write_note_first"), { error: true }); }
    return immediate({ action: "note", key: s.key, note }, btn, true);
  }
  if (kind === "run") return immediate({ action: "run-now", key: s.key }, btn, true);
  if (kind === "done") {
    const box = $(".dr-done");
    const ev = $("#d-evidence");
    if (box.hidden && !s.evidence) { box.hidden = false; ev.focus(); $(".lbl", btn).textContent = t("drawer.confirm_done"); return; }
    const evidence = ev.value.trim();
    if (!evidence && !s.evidence) { ev.focus(); return toast(t("srv.evidence_required"), { error: true }); }
    return closeFromDrawer({ action: "done", key: s.key, evidence, note }, t("toast.done", { id: s.id || t("common.task") }));
  }
  if (kind === "cancel") {
    if (!S.closingAsk) { S.closingAsk = true; btn.textContent = t("drawer.confirm_cancel"); return; }
    return closeFromDrawer({ action: "cancel", key: s.key, note }, t("toast.cancelled", { id: s.id || t("common.task") }));
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
    toast(okText(res));
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
  box.innerHTML = `<label class="sr" for="ev-${esc(key)}">${esc(t("drawer.evidence"))}</label><input id="ev-${esc(key)}" placeholder="${esc(t("row.evidence_placeholder"))}" autocomplete="off">
    <button type="button" class="btn-ok needs-net" data-act="inline-ok" data-key="${esc(key)}">${esc(t("drawer.mark_done"))}</button><button type="button" class="btn-quiet" data-act="inline-no">${esc(t("row.not_yet"))}</button>`;
  li.after(box);
  const input = $("input", box);
  input.focus();
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $('[data-act="inline-ok"]', box).click(); } if (e.key === "Escape") box.remove(); });
}
function inlineOk(btn) {
  const box = btn.closest(".inline-done");
  const evidence = $("input", box).value.trim();
  if (!evidence) { $("input", box).focus(); return toast(t("srv.evidence_required"), { error: true }); }
  const key = btn.dataset.key;
  box.remove();
  const restore = hideRows(key);
  bumpCount("today", -1);
  const id = key.split("/")[1];
  closing({ action: "done", key, evidence }, { label: t("toast.done", { id: /^[A-Z]-\d+$/.test(id) ? id : t("common.task") }), restore: () => { restore(); bumpCount("today", 1); }, after: () => softRefresh() });
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
    sel.innerHTML = `<option value="">${esc(t("new.inbox"))}</option>` + p.items.map((x) => `<option value="${esc(x.slug)}">${esc(x.name)}</option>`).join("");
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
  $("#new-help").textContent = t(`new.help_${kind}`);
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
  btn.disabled = true; btn.textContent = t("new.creating");
  try {
    const res = await post("/api/create", body);
    $("#new-dialog").close();
    toast(okText(res), res.key ? { action: () => go(hashFor(S.route.view, S.route.rest, { ...S.route.q, task: res.key })), actionLabel: t("common.open"), ms: 7000 } : {});
    softRefresh();
  } catch (err) {
    const el = $("#new-error"); el.textContent = err.message; el.hidden = false;
  } finally { btn.disabled = false; btn.textContent = t("new.submit"); }
}

// ── counts and refresh ──────────────────────────────────────────────────────
function updateCounts(d) {
  const set = (k, v) => $$(`[data-count="${k}"]`).forEach((el) => { el.textContent = v ? String(v) : ""; });
  set("today", d.mine.today.length + d.mine.overdue.length + d.review.length);
  set("decisions", d.decisions.count);
  set("activity", d.closed_24h);
}
function bumpCount(k, delta) {
  $$(`[data-count="${k}"]`).forEach((el) => { const v = Math.max(0, (parseInt(el.textContent, 10) || 0) + delta); el.textContent = v ? String(v) : ""; });
}
async function refreshCounts() {
  try { const d = await api("/api/today"); S.today = d; updateCounts(d); } catch (_) { /* offline bar */ }
}
let softTimer = null;
function softRefresh() {
  clearTimeout(softTimer);
  softTimer = setTimeout(async () => {
    if (S.armed || S.editing) return;
    const def = VIEWS[S.route.view] || VIEWS.today;
    if (S.route.view === "tree") { S.tree?.reload(); refreshCounts(); return; }
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
function listRows() { return $$("#main .row[data-key], #main .grid tbody tr").filter((r) => !r.hidden && r.offsetParent !== null); }
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
    const map = { d: "#/today", e: "#/decisions", p: "#/projects", a: "#/activity", t: "#/tree", l: "#/tasks" };
    if (map[k]) { e.preventDefault(); go(map[k]); }
    return;
  }
  const inStack = S.route.view === "decisions" && $("#drawer-wrap").hidden && S.decisions?.items.length;
  if (k === "g") { S.gAt = Date.now(); return; }
  if (k === "/") { e.preventDefault(); return focusSearch(); }
  if (k === "n") { e.preventDefault(); return openNew(); }
  if (k === "?") { e.preventDefault(); return $("#keys-dialog").showModal(); }
  if (k === "l") { e.preventDefault(); return toggleLang(); }
  if (k === "z" && S.lastUndo && Date.now() < S.lastUndo.until) { e.preventDefault(); return S.lastUndo.undo(); }
  if (S.route.view === "tree" && S.tree && (k === "f" || k === "u")) { e.preventDefault(); return S.tree.key(k); }
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
  if (!el) {
    // a click anywhere on a row or a table line opens it (the link stays for keyboard users)
    const line = e.target.closest("#main .row[data-key], #main [data-href]");
    if (line && !e.target.closest("a, button, input, textarea, summary")) {
      const a = line.dataset.href ? null : $(".ttl a", line);
      if (line.dataset.href) go(line.dataset.href); else if (a) a.click();
    }
    return;
  }
  const act = el.dataset.act;
  switch (act) {
    case "check": return inlineDone(el);
    case "inline-ok": return inlineOk(el);
    case "inline-no": return el.closest(".inline-done").remove();
    case "pick": S.decIdx = Number(el.dataset.i); $("#stack")?.classList.remove("show-list"); return drawStack();
    case "decide": return armOrCommit(el.dataset.v);
    case "skip": case "next": return moveDecision(1);
    case "prev": return moveDecision(-1);
    case "stack-filter": S.stackFilter = S.stackFilter === "overdue" ? "all" : "overdue"; ls.set(LS.stackFilter, S.stackFilter); S.decIdx = 0; return drawStack();
    case "stack-group": S.stackGroup = S.stackGroup === "project" ? "due" : "project"; ls.set(LS.stackGroup, S.stackGroup); S.decIdx = 0; return drawStack();
    case "stack-all": S.stackFilter = "all"; ls.set(LS.stackFilter, "all"); return drawStack();
    case "stack-toggle": return $("#stack")?.classList.toggle("show-list");
    case "reload": return softRefresh();
    case "theme": return cycleTheme();
    case "lang": return toggleLang();
    case "tog": {
      const li = el.closest("li");
      const collapsed = li.toggleAttribute("data-collapsed");
      el.setAttribute("aria-expanded", String(!collapsed));
      return;
    }
    case "copy": navigator.clipboard?.writeText(el.dataset.text).then(() => toast(t("common.copied"))); return;
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
  const s = S.drawer;
  const kind = btn.dataset.v;
  if (!(S.armed && S.armed.kind === kind && S.armed.drawer && Date.now() < S.armed.until)) {
    $$('[data-act="d-decide"]').forEach((b) => { b.classList.remove("armed"); $(".lbl", b).textContent = decLabel(b.dataset.v); });
    S.armed = { kind, until: Date.now() + ARM_MS, drawer: true };
    btn.classList.add("armed");
    $(".lbl", btn).textContent = t(kind === "accept" ? "dec.confirm_accept" : "dec.confirm_reject");
    setTimeout(() => { if (S.armed?.drawer && Date.now() >= S.armed.until) S.armed = null; }, ARM_MS + 50);
    return;
  }
  S.armed = null;
  const note = ($("#d-note")?.value || "").trim();
  closeFromDrawer({ action: "decide", key: s.key, accepted: kind === "accept", note }, t(kind === "accept" ? "toast.accepted" : "toast.rejected", { id: s.id }));
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
    const s = S.drawer;
    const btn = $('button[type="submit"]', e.target);
    btn.disabled = true;
    try {
      const res = await post("/api/actions", { action: "edit", key: s.key, mtime_ns: s.mtime_ns, title: f.title.value, priority: f.priority.value, due: f.due.value, body: f.body.value });
      toast(okText(res));
      S.editing = false;
      const k = s.key; S.drawer = null; await openDrawer(k);
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
document.addEventListener("touchstart", (e) => { if (e.target.closest(".stack-body")) touchX = e.touches[0].clientX; }, { passive: true });
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
    const task = await api(`/api/task/${det.dataset.key.split("/").map(encodeURIComponent).join("/")}`);
    $(".full-body", det).innerHTML = md(cleanBody(task.body, task.title));
  } catch (err) { $(".full-body", det).textContent = t("err.load", { msg: err.message }); }
}, true);

// ── theme and language ──────────────────────────────────────────────────────
function themeMode() { return ls.get(LS.theme) || "auto"; }
function themeLabel() { return t("theme.label", { mode: t(`theme.${themeMode()}`) }); }
function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
  $("#theme-label").textContent = themeLabel();
  window.dispatchEvent(new Event("agentos-theme"));
}
function cycleTheme() {
  const order = ["auto", "light", "dark"];
  const next = order[(order.indexOf(themeMode()) + 1) % order.length];
  ls.set(LS.theme, next);
  applyTheme(next);
  $$('[data-act="theme"]').forEach((b) => { b.lastChild.textContent = themeLabel(); });
}
function syncLangUi() {
  $$("[data-lang]").forEach((b) => b.classList.toggle("on", b.dataset.lang === getLang()));
  $("#theme-label").textContent = themeLabel();
  if (S.meta) $("#brand-name").textContent = S.meta.product || t("common.panel");
  syncUpdateUi();
}
/** Sidebar link shown only when the daily check found a newer release (off: [updates] check = false). */
function syncUpdateUi() {
  const link = $("#update-link");
  const up = S.meta?.update;
  if (!link) return;
  if (!up?.available || !/^https:\/\/github\.com\//.test(up.url || "")) { link.hidden = true; return; }
  const vars = { version: up.latest, current: S.meta.version || "" };
  link.href = up.url;
  link.title = t("updates.available_title", vars);
  $("#update-label").textContent = t("updates.available", vars);
  link.hidden = false;
}
async function toggleLang() {
  await setLang(getLang() === "pl" ? "en" : "pl");
  syncLangUi();
  delete $("#main").dataset.ready;
  if (S.drawer && !S.editing) drawDrawer();
  await route();
}

// ── boot ────────────────────────────────────────────────────────────────────
async function boot() {
  S.lastVisit = ls.get(LS.visit);
  S.stackFilter = ls.get(LS.stackFilter) === "overdue" ? "overdue" : "all";
  S.stackGroup = ls.get(LS.stackGroup) === "project" ? "project" : "due";
  try { S.meta = await api("/api/meta"); } catch (_) { /* offline bar shows */ }
  await initI18n(S.meta?.language);
  const qsTheme = new URLSearchParams(location.search).get("theme");
  if (qsTheme) ls.set(LS.theme, qsTheme);
  applyTheme(qsTheme || themeMode());
  syncLangUi();
  document.addEventListener("click", onClick);
  document.addEventListener("submit", onSubmit);
  document.addEventListener("keydown", onKey);
  $("#new-form").addEventListener("change", (e) => { if (e.target.name === "kind") syncNewKind(); });
  $("#new-btn").addEventListener("click", openNew);
  $("#theme-btn").addEventListener("click", cycleTheme);
  $("#lang-btn").addEventListener("click", toggleLang);
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
  await route();
  if (S.route.view !== "today") refreshCounts();
  setInterval(() => { if (document.visibilityState === "visible" && idle()) softRefresh(); }, REFRESH_MS);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && idle()) softRefresh(); });
}
boot();

// exported for the in-browser checks in tests (window.agentosPanel)
window.agentosPanel = { t, tn, fmtDay, joinList, getLang, applyStatic };
