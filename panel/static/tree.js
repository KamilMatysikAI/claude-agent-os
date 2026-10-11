// Tree: who works on what. Owner -> projects -> roles (agents and you) -> open tasks,
// drawn on an SVG canvas with organic curves. Same data as every other screen
// (/api/orgtree regroups the one workspace scan). No chart library: the panel works
// offline and over a private network from a phone, so a CDN would be a single point
// of failure for this view.
//
// Colour encodes state only (waiting, agent at work, blocked or overdue, decision,
// yours); a project is text, never a colour. Three layouts from one ordering of the
// leaves: compact (one row per project, roles as badges, the default because it fits a
// whole portfolio on one screen), expanded (horizontal tree) and radial.

const SVGNS = "http://www.w3.org/2000/svg";
const LS_LAYOUT = "agentos.treeLayout";
const LAYOUTS = ["compact", "expanded", "radial"];

function readLayout() {
  try { const v = localStorage.getItem(LS_LAYOUT); return LAYOUTS.includes(v) ? v : "compact"; } catch (_) { return "compact"; }
}
const tok = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function el(name, attrs) {
  const e = document.createElementNS(SVGNS, name);
  for (const a in attrs) if (attrs[a] != null) e.setAttribute(a, attrs[a]);
  return e;
}

export function mountTree(main, ctx) {
  const { t, tn } = ctx;
  let DATA = null;
  let FILTER = "all";
  let LAYOUT = readLayout();
  let COLLAPSED = new Set();      // keys of nodes whose children are hidden (expanded/radial)
  const OPEN_ROLES = new Set();   // compact layout: project/role badges shown with tasks
  const VIEW = { x: 0, y: 0, k: 1 };
  let dragged = false;
  let refreshTimer = null;
  let resizeTimer = null;

  main.innerHTML = `
    <div class="tree-bar">
      <span class="stats" id="tree-stats">${esc(t("common.loading"))}</span><span class="spacer"></span>
      <button type="button" class="btn" id="tree-layout" title="${esc(t("tree.layout_title"))}"></button>
      <button type="button" class="btn" id="tree-fit" title="${esc(t("tree.fit_title"))}">${esc(t("tree.fit"))}</button>
      <button type="button" class="btn" id="tree-png" title="${esc(t("tree.png_title"))}">${esc(t("tree.png"))}</button>
      <button type="button" class="btn" id="tree-refresh">${esc(t("tree.refresh"))}</button>
    </div>
    <div class="tree-bar tree-filters" role="group" aria-label="${esc(t("tree.filter_label"))}">
      ${["all", "mine", "in_progress", "overdue", "blocked"].map((f) => `<button type="button" class="chip" data-filter="${f}" aria-pressed="${f === "all"}">${esc(t(`tree.f_${f}`))}</button>`).join("")}
      <span class="gap"></span>
      <button type="button" class="btn" id="tree-expand">${esc(t("tree.expand"))}</button>
      <button type="button" class="btn" id="tree-collapse">${esc(t("tree.collapse"))}</button>
    </div>
    <div class="tree-phone">
      <p>${esc(t("tree.phone_text"))}</p>
      <a class="btn-primary" href="#/projects">${esc(t("tree.phone_table"))}</a>
      <button type="button" class="btn" id="tree-force">${esc(t("tree.phone_anyway"))}</button>
    </div>
    <div class="tree-area" id="tree-area">
      <div class="tree-loading" id="tree-loading">${esc(t("tree.loading"))}</div>
      <svg id="tree-svg" role="img" aria-label="${esc(t("tree.svg_label"))}"></svg>
      <div class="tree-legend">
        <div><i class="lt-wait"></i>${esc(t("tree.lg_wait"))}</div>
        <div><i class="lt-work"></i>${esc(t("tree.lg_work"))}</div>
        <div><i class="lt-stop"></i>${esc(t("tree.lg_stop"))}</div>
        <div><i class="lt-dec"></i>${esc(t("tree.lg_dec"))}</div>
        <div><i class="lt-mine"></i>${esc(t("tree.lg_mine"))}</div>
      </div>
      <div class="tree-foot" id="tree-foot"></div>
    </div>
    <div class="tree-tip" id="tree-tip" role="tooltip"></div>`;

  const svg = main.querySelector("#tree-svg");
  const tip = main.querySelector("#tree-tip");
  const q = (s) => main.querySelector(s);

  // ── labels ────────────────────────────────────────────────────────────────
  const projectName = (p) => (p.inbox ? t("tree.inbox") : p.name);
  const roleLabel = (r) => ctx.roleName(r.role);
  function projectCaption(p) {
    const bits = [tn("tree.n_open", p.open)];
    if (p.mine) bits.push(tn("tree.n_yours", p.mine));
    if (p.blocked) bits.push(tn("tree.n_blocked", p.blocked));
    if (p.overdue) bits.push(tn("tree.n_overdue", p.overdue));
    return bits.join(" · ");
  }
  function taskLabel(d) {
    const flags = (d.overdue_days > 0 ? ` · ${tn("tree.days_late", d.overdue_days)}` : "") + (d.decision ? ` · ${t("tree.decision")}` : "");
    const title = d.title.length > 90 ? d.title.slice(0, 89) + "…" : d.title;
    return `${d.id ? d.id + " · " : ""}${title}${flags}`;
  }
  function nodeLabel(d) {
    if (d.kind === "root") return d.name;
    if (d.kind === "project") return projectName(d);
    if (d.kind === "role") return `${roleLabel(d)} (${d.open})`;
    return taskLabel(d);
  }

  // ── colours: state only ───────────────────────────────────────────────────
  function taskColor(d) {
    if (d.decision) return tok("--decide");
    if (d.status === "blocked" || d.overdue_days > 0) return tok("--stop");
    if (d.status === "in_progress") return tok("--agent");
    if (d.human) return tok("--text");
    return tok("--text-2");
  }
  function nodeColor(n) {
    const d = n.data;
    if (d.kind === "root") return tok("--text");
    if (d.kind === "task") return taskColor(d);
    if (d.kind === "role" && d.role === "human") return tok("--text");
    if (d.kind === "project") return projectColor(d);
    return tok("--line-2");
  }
  // red only when at least a third of the open tasks are overdue (the "health" rule on
  // Projects); otherwise nearly every project would glow red
  function projectColor(p) {
    if (p.overdue * 3 >= Math.max(p.open, 1)) return tok("--stop");
    return p.in_progress > 0 ? tok("--agent") : tok("--text-2");
  }
  const width = (d) => Math.max(1.1, Math.min(9, Math.sqrt(d.open || 1) * 1.7));

  // ── filter ────────────────────────────────────────────────────────────────
  function matches(d) {
    if (FILTER === "all") return true;
    if (FILTER === "mine") return d.human;
    if (FILTER === "in_progress") return d.status === "in_progress";
    if (FILTER === "overdue") return d.overdue_days > 0;
    if (FILTER === "blocked") return d.status === "blocked";
    return true;
  }
  // the filter works on leaves; branches without a matching leaf disappear, otherwise
  // "Mine" would show a forest of empty role branches
  function filtered(n) {
    if (n.kind === "task") return matches(n) ? { ...n } : null;
    const children = (n.children || []).map(filtered).filter(Boolean);
    if (!children.length && n.kind !== "root") return null;
    return { ...n, children };
  }
  const nodeKey = (d, parent) => `${parent}/${d.slug ?? ""}${d.role ?? ""}${d.id || d.key || d.name || ""}`;

  // ── layout (expanded and radial share it) ─────────────────────────────────
  function layout(root) {
    const nodes = []; const edges = [];
    let rowIdx = 0;
    const STEP = 26; const PROJECT_GAP = 0.9;
    const COLS = [0, 330, 720, 990];
    function walk(d, level, parentKey, proj) {
      const key = nodeKey(d, parentKey);
      const collapsed = COLLAPSED.has(key);
      const kids = collapsed ? [] : (d.children || []);
      const n = { data: d, level, key, collapsed, hasKids: (d.children || []).length > 0, proj, x: COLS[Math.min(level, COLS.length - 1)], y: 0 };
      nodes.push(n);
      if (!kids.length) { n.y = rowIdx * STEP; rowIdx += 1; }
      else {
        const below = kids.map((c, i) => { if (level === 0 && i > 0) rowIdx += PROJECT_GAP; return walk(c, level + 1, key, level === 0 ? i : proj); });
        n.y = (below[0].y + below[below.length - 1].y) / 2;
        below.forEach((b) => edges.push({ from: n, to: b }));
      }
      return n;
    }
    walk(root, 0, "", 0);
    return { nodes, edges, height: Math.max(1, rowIdx) * STEP };
  }
  function toRadial(l) {
    const H = Math.max(l.height, 1);
    const R = Math.max(560, (H / (2 * Math.PI)) * 1.5);
    const RINGS = [0, R * 0.46, R * 0.82, R];
    l.nodes.forEach((n) => {
      const a = (n.y / H) * Math.PI * 2 - Math.PI / 2;
      n.angle = a; n.radius = RINGS[Math.min(n.level, RINGS.length - 1)];
      n.deg = (a * 180) / Math.PI; n.rx = Math.cos(a) * n.radius; n.ry = Math.sin(a) * n.radius;
    });
  }

  // ── node interaction ──────────────────────────────────────────────────────
  function bind(g, d, onActivate, label) {
    g.setAttribute("tabindex", "0");
    g.setAttribute("role", "button");
    g.setAttribute("aria-label", label);
    g.addEventListener("mouseenter", (ev) => showTip(ev, d));
    g.addEventListener("mousemove", moveTip);
    g.addEventListener("mouseleave", hideTip);
    g.addEventListener("click", (ev) => { ev.stopPropagation(); if (dragged) return; onActivate(); });
    g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onActivate(); } });
  }
  function openTask(d) { hideTip(); ctx.openTask(d); }

  // ── compact layout: one row per project, roles as badges ──────────────────
  const W_PROJECT = 320; const X_BADGES = 370; const W_BADGE = 108;
  function drawCompact(root) {
    svg.innerHTML = "";
    const cam = el("g", { id: "tree-cam" }); svg.appendChild(cam);
    const gEdges = el("g"); const gRows = el("g");
    cam.appendChild(gEdges); cam.appendChild(gRows);
    const ROW = 40; const ROW_TASK = 26;
    let y = 0;
    const placed = [];
    (root.children || []).forEach((p) => {
      const py = y;
      placed.push({ p, y: py });
      const g = el("g", { class: "node", transform: `translate(0,${py})` });
      g.appendChild(el("rect", { class: "hit", x: -14, y: -ROW / 2 + 2, width: W_PROJECT + 10, height: ROW - 4, rx: 6 }));
      const c = projectColor(p);
      g.appendChild(el("circle", { r: 6, fill: c, stroke: c }));
      const name = el("text", { class: "label big", x: 15, dy: "-1" }); name.textContent = projectName(p); g.appendChild(name);
      const cap = el("text", { class: "caption", x: 15, dy: "13" }); cap.textContent = projectCaption(p); g.appendChild(cap);
      bind(g, p, () => {
        const keys = (p.children || []).map((r) => `${p.slug}/${r.role}`);
        const open = keys.some((k) => OPEN_ROLES.has(k));
        keys.forEach((k) => (open ? OPEN_ROLES.delete(k) : OPEN_ROLES.add(k)));
        draw();
      }, `${projectName(p)}: ${projectCaption(p)}`);
      gRows.appendChild(g);
      (p.children || []).forEach((r, j) => {
        const k = `${p.slug}/${r.role}`;
        const open = OPEN_ROLES.has(k);
        const x = X_BADGES + j * W_BADGE;
        const mine = r.role === "human";
        const b = el("g", { class: "node", transform: `translate(${x},${py})` });
        b.appendChild(el("rect", { class: "badge", x: 0, y: -13, width: W_BADGE - 10, height: 26, rx: 6,
          fill: open ? tok("--surface-3") : tok("--surface"), stroke: mine ? tok("--text") : tok("--line-2"), "stroke-width": mine ? 1.5 : 1 }));
        const txt = el("text", { class: "label", x: 10, dy: "4.5" });
        const lbl = roleLabel(r);
        txt.textContent = `${lbl.length > 10 ? lbl.slice(0, 9) + "…" : lbl} ${r.open}`;
        b.appendChild(txt);
        if (r.in_progress > 0) b.appendChild(el("circle", { cx: W_BADGE - 19, cy: 0, r: 4, fill: tok("--agent") }));
        else if (r.overdue > 0 || r.blocked > 0) b.appendChild(el("circle", { cx: W_BADGE - 19, cy: 0, r: 4, fill: tok("--stop") }));
        bind(b, r, () => { (OPEN_ROLES.has(k) ? OPEN_ROLES.delete(k) : OPEN_ROLES.add(k)); draw(); }, `${projectName(p)}, ${lbl}: ${tn("tree.n_open", r.open)}`);
        gRows.appendChild(b);
      });
      y += ROW;
      (p.children || []).forEach((r) => {
        if (!OPEN_ROLES.has(`${p.slug}/${r.role}`)) return;
        (r.children || []).forEach((d) => {
          const g2 = el("g", { class: "node", transform: `translate(${X_BADGES},${y})` });
          g2.appendChild(el("rect", { class: "hit", x: -8, y: -ROW_TASK / 2, width: 680, height: ROW_TASK, rx: 5 }));
          g2.appendChild(el("circle", { cx: 4, r: 4, fill: taskColor(d) }));
          const tt = el("text", { class: "label", x: 16, dy: "4.5" }); tt.textContent = `${roleLabel(r)}: ${taskLabel(d)}`; g2.appendChild(tt);
          bind(g2, d, () => openTask(d), taskLabel(d));
          gRows.appendChild(g2);
          y += ROW_TASK;
        });
      });
      y += 6;
    });
    const yRoot = Math.max(0, y - 6 - ROW) / 2;
    placed.forEach(({ p, y: py }) => {
      gEdges.appendChild(el("path", { class: "link", d: `M-150,${yRoot} C-70,${yRoot} -70,${py} 0,${py}`,
        stroke: p.overdue > 0 ? tok("--line-2") : tok("--line"), "stroke-width": Math.max(1.1, Math.min(7, Math.sqrt(p.open || 1) * 1.3)), "stroke-opacity": 0.9 }));
    });
    const rg = el("g", { class: "node", transform: `translate(-150,${yRoot})` });
    rg.appendChild(el("circle", { r: 11, fill: tok("--text") }));
    const rt = el("text", { class: "label big", x: -20, dy: "-1", "text-anchor": "end" }); rt.textContent = root.name; rg.appendChild(rt);
    const rc = el("text", { class: "caption", x: -20, dy: "13", "text-anchor": "end" }); rc.textContent = tn("tree.n_open", root.open); rg.appendChild(rc);
    rg.addEventListener("mouseenter", (ev) => showTip(ev, root)); rg.addEventListener("mousemove", moveTip); rg.addEventListener("mouseleave", hideTip);
    gRows.appendChild(rg);
    q("#tree-loading").hidden = true;
    applyView();
  }

  // ── expanded and radial layouts ───────────────────────────────────────────
  function draw() {
    if (!DATA) return;
    const root = filtered(DATA.root) || { ...DATA.root, children: [] };
    if (LAYOUT === "compact") { drawCompact(root); return; }
    const l = layout(root);
    if (LAYOUT === "radial") toRadial(l);
    svg.innerHTML = "";
    const cam = el("g", { id: "tree-cam" }); svg.appendChild(cam);
    const gEdges = el("g"); const gNodes = el("g");
    cam.appendChild(gEdges); cam.appendChild(gNodes);
    const pos = (n) => (LAYOUT === "radial" ? [n.rx, n.ry] : [n.x, n.y]);
    l.edges.forEach((e) => {
      const [x1, y1] = pos(e.from); const [x2, y2] = pos(e.to);
      let dd;
      if (LAYOUT === "radial") dd = `M${x1},${y1} Q${((x1 + x2) / 2) * 0.72},${((y1 + y2) / 2) * 0.72} ${x2},${y2}`;
      else { const sx = (x1 + x2) / 2; dd = `M${x1},${y1} C${sx},${y1} ${sx},${y2} ${x2},${y2}`; }
      gEdges.appendChild(el("path", { class: "link", d: dd, stroke: nodeColor(e.to), "stroke-width": width(e.to.data), "stroke-opacity": e.to.data.kind === "task" ? 0.38 : 0.55 }));
    });
    l.nodes.forEach((n) => {
      const [x, y] = pos(n);
      const d = n.data;
      const g = el("g", { class: "node", transform: LAYOUT === "radial" ? `rotate(${n.deg}) translate(${n.radius},0)` : `translate(${x},${y})` });
      const color = nodeColor(n);
      const r = d.kind === "root" ? 13 : d.kind === "project" ? 9 : d.kind === "role" ? 6.5 : 4.5;
      g.appendChild(el("circle", { r, fill: n.collapsed ? tok("--bg") : color, stroke: color, "stroke-width": n.collapsed ? 2 : 1.2 }));
      // a collapsed node shows how many tasks it hides, otherwise collapsing hides the scale of the work
      if (n.collapsed && (d.open || 0) > 0) {
        g.appendChild(el("circle", { r: 8.5, fill: color, opacity: 0.92 }));
        const c = el("text", { class: "counter", "text-anchor": "middle", dy: "3.4", transform: LAYOUT === "radial" ? `rotate(${-n.deg})` : null });
        c.textContent = d.open; g.appendChild(c);
      }
      const left = LAYOUT === "radial" && Math.cos(n.angle) < 0;
      const dx = (left ? -1 : 1) * (r + 7);
      const flip = left ? "rotate(180)" : null;
      const label = el("text", { class: "label" + (d.kind === "root" || d.kind === "project" ? " big" : ""), x: dx,
        dy: d.kind === "task" || d.kind === "role" ? "3.6" : "-1", "text-anchor": left ? "end" : "start", transform: flip });
      label.textContent = nodeLabel(d); g.appendChild(label);
      if (d.kind === "root" || d.kind === "project") {
        const cap = el("text", { class: "caption", x: dx, dy: "13", "text-anchor": left ? "end" : "start", transform: flip });
        cap.textContent = d.kind === "root" ? tn("tree.n_open", d.open) : projectCaption(d);
        g.appendChild(cap);
      }
      const w = label.textContent.length * 6.4 + 16;
      g.insertBefore(el("rect", { class: "hit", x: left ? -(w + r + 6) : -(r + 6), y: -13, width: w + r + 12, height: 26, rx: 5 }), g.firstChild);
      bind(g, d, () => {
        if (!n.hasKids) { if (d.kind === "task") openTask(d); return; }
        (COLLAPSED.has(n.key) ? COLLAPSED.delete(n.key) : COLLAPSED.add(n.key));
        draw();
      }, nodeLabel(d));
      gNodes.appendChild(g);
    });
    q("#tree-loading").hidden = true;
    applyView();
  }

  // ── tooltip ───────────────────────────────────────────────────────────────
  function showTip(ev, d) {
    let h = "";
    if (d.kind === "root") {
      h = `<h4>${esc(d.name)}</h4><div class="m">${esc(t("tree.tip_root", { projects: DATA.stats.projects, open: d.open, working: d.in_progress }))}</div>`;
    } else if (d.kind === "project") {
      h = `<h4>${esc(projectName(d))}</h4>${d.goal ? `<div class="m">${esc(d.goal)}</div>` : ""}
        <div class="rz">${esc(t("tree.tip_counts", { open: d.open, working: d.in_progress, blocked: d.blocked, overdue: d.overdue }))}<br>
        <span class="m">${esc(tn("tree.n_yours", d.mine))}${d.decisions ? ` · ${esc(tn("tree.n_decisions", d.decisions))}` : ""}</span></div>
        ${d.working_titles && d.working_titles.length ? `<div class="rz">${esc(t("tree.tip_working"))}<br>${d.working_titles.map((x) => "• " + esc(x)).join("<br>")}</div>` : ""}`;
    } else if (d.kind === "role") {
      h = `<h4>${esc(roleLabel(d))}</h4><div class="m">${esc(t("tree.tip_counts", { open: d.open, working: d.in_progress, blocked: d.blocked, overdue: d.overdue }))}</div>`;
    } else {
      h = `<h4>${esc(d.id)} ${esc(d.title)}</h4><div class="m">${esc(ctx.statusName(d.status))} · ${esc(ctx.prioName(d.priority))}${d.due ? ` · ${esc(t("tree.tip_due", { date: ctx.fmtDay(d.due) }))}` : ""}</div>
        ${d.overdue_days > 0 ? `<div class="rz stop">${esc(tn("tree.days_late", d.overdue_days))}</div>` : ""}
        ${d.decision ? `<div class="rz dec">${esc(t("tree.tip_decision"))}</div>` : ""}`;
    }
    tip.innerHTML = h;
    tip.classList.add("on");
    moveTip(ev);
  }
  function moveTip(ev) {
    const m = 16; const box = tip.getBoundingClientRect();
    let x = ev.clientX + m; let y = ev.clientY + m;
    if (x + box.width > innerWidth - 8) x = ev.clientX - box.width - m;
    if (y + box.height > innerHeight - 8) y = ev.clientY - box.height - m;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${Math.max(8, y)}px`;
  }
  function hideTip() { tip.classList.remove("on"); }

  // ── camera: pan, zoom, fit ────────────────────────────────────────────────
  function applyView() {
    const cam = svg.querySelector("#tree-cam");
    if (cam) cam.setAttribute("transform", `translate(${VIEW.x},${VIEW.y}) scale(${VIEW.k})`);
  }
  function fit() {
    const cam = svg.querySelector("#tree-cam");
    if (!cam) return;
    const b = cam.getBBox(); const r = svg.getBoundingClientRect();
    if (!b.width || !b.height || !r.width) return;
    const margin = 40; const minReadable = LAYOUT === "compact" ? 0.75 : 0.5;
    // compact is effectively a list: fit the width, scroll the height with the wheel
    const ideal = LAYOUT === "compact"
      ? Math.min((r.width - margin * 2) / b.width, 1.1)
      : Math.min((r.width - margin * 2) / b.width, (r.height - margin * 2) / b.height, 1.6);
    // squeezing a tall tree onto the screen gives 4 px text; below the threshold show the
    // top in a readable scale and leave scrolling
    VIEW.k = Math.max(ideal, minReadable);
    if (LAYOUT === "compact") {
      VIEW.x = Math.max(margin - b.x * VIEW.k, (r.width - b.width * VIEW.k) / 2 - b.x * VIEW.k);
      VIEW.y = margin / 2 - b.y * VIEW.k;
    } else if (ideal >= minReadable) {
      VIEW.x = (r.width - b.width * VIEW.k) / 2 - b.x * VIEW.k;
      VIEW.y = (r.height - b.height * VIEW.k) / 2 - b.y * VIEW.k;
    } else {
      VIEW.x = margin - b.x * VIEW.k;
      VIEW.y = margin - b.y * VIEW.k;
    }
    applyView();
  }
  function zoom(k, at) {
    k = Math.max(0.15, Math.min(4, k));
    VIEW.x = at.x - (at.x - VIEW.x) * (k / VIEW.k);
    VIEW.y = at.y - (at.y - VIEW.y) * (k / VIEW.k);
    VIEW.k = k;
    applyView();
  }
  // pointer capture would redirect the node's click to the canvas, so capture starts only
  // after a real move of more than 4 px; until then the gesture is a click on the node
  const fingers = new Map();
  let drag = null; let pinch = null;
  const dist = () => { const [a, b] = [...fingers.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  const mid = () => { const [a, b] = [...fingers.values()]; const r = svg.getBoundingClientRect(); return { x: (a.x + b.x) / 2 - r.left, y: (a.y + b.y) / 2 - r.top }; };
  svg.addEventListener("pointerdown", (ev) => {
    fingers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (fingers.size === 2) {
      drag = null; dragged = true; pinch = { d: dist(), k: VIEW.k };
      fingers.forEach((_, id) => { try { svg.setPointerCapture(id); } catch (_) { /* gone */ } });
    } else if (fingers.size === 1) {
      drag = { x: ev.clientX - VIEW.x, y: ev.clientY - VIEW.y, sx: ev.clientX, sy: ev.clientY, id: ev.pointerId };
      dragged = false;
    }
  });
  svg.addEventListener("pointermove", (ev) => {
    if (fingers.has(ev.pointerId)) fingers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (fingers.size === 2 && pinch) { const d = dist(); if (d > 0 && pinch.d > 0) zoom(pinch.k * (d / pinch.d), mid()); return; }
    if (!drag) return;
    if (!dragged) {
      if (Math.hypot(ev.clientX - drag.sx, ev.clientY - drag.sy) < 4) return;
      dragged = true; svg.classList.add("dragging"); hideTip();
      try { svg.setPointerCapture(drag.id); } catch (_) { /* gone */ }
    }
    VIEW.x = ev.clientX - drag.x; VIEW.y = ev.clientY - drag.y;
    applyView();
  });
  ["pointerup", "pointercancel"].forEach((name) => svg.addEventListener(name, (ev) => {
    fingers.delete(ev.pointerId);
    if (fingers.size < 2) pinch = null;
    if (fingers.size === 0) { drag = null; svg.classList.remove("dragging"); }
  }));
  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    if (LAYOUT === "compact" && !ev.ctrlKey) { VIEW.y -= ev.deltaY; VIEW.x -= ev.deltaX; applyView(); return; }
    const r = svg.getBoundingClientRect();
    zoom(VIEW.k * Math.exp(-ev.deltaY * 0.0016), { x: ev.clientX - r.left, y: ev.clientY - r.top });
  }, { passive: false });

  // ── controls ──────────────────────────────────────────────────────────────
  function keysFrom(level) {
    const out = new Set();
    (function walk(d, lv, parent) {
      const k = nodeKey(d, parent);
      if (lv >= level && (d.children || []).length) out.add(k);
      (d.children || []).forEach((c) => walk(c, lv + 1, k));
    })(DATA.root, 0, "");
    return out;
  }
  const allRoleKeys = () => { const s = new Set(); (DATA.root.children || []).forEach((p) => (p.children || []).forEach((r) => s.add(`${p.slug}/${r.role}`))); return s; };
  function setLayoutLabel() { q("#tree-layout").textContent = t(`tree.layout_${LAYOUT}`); }
  q("#tree-expand").onclick = () => { COLLAPSED = new Set(); allRoleKeys().forEach((k) => OPEN_ROLES.add(k)); draw(); fit(); };
  q("#tree-collapse").onclick = () => { COLLAPSED = keysFrom(1); OPEN_ROLES.clear(); draw(); fit(); };
  q("#tree-fit").onclick = fit;
  q("#tree-refresh").onclick = () => load(true);
  q("#tree-layout").onclick = () => switchLayout();
  q("#tree-force").onclick = () => { ctx.onForce(); if (DATA) { draw(); fit(); } };
  main.querySelectorAll("[data-filter]").forEach((b) => {
    b.onclick = () => {
      main.querySelectorAll("[data-filter]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      FILTER = b.dataset.filter;
      // a narrowing filter opens the tasks by itself, otherwise "Mine" shows empty branches
      COLLAPSED = FILTER === "all" ? keysFrom(2) : new Set();
      OPEN_ROLES.clear();
      if (FILTER !== "all") allRoleKeys().forEach((k) => OPEN_ROLES.add(k));
      draw(); fit();
    };
  });
  function switchLayout() {
    LAYOUT = LAYOUTS[(LAYOUTS.indexOf(LAYOUT) + 1) % LAYOUTS.length];
    try { localStorage.setItem(LS_LAYOUT, LAYOUT); } catch (_) { /* private mode */ }
    setLayoutLabel(); draw(); fit();
  }
  setLayoutLabel();

  // PNG: SVG -> image -> canvas. No library, works offline; the background is painted in,
  // a transparent PNG on social media looks like a bug
  q("#tree-png").onclick = () => {
    const cam = svg.querySelector("#tree-cam");
    if (!cam) return;
    const b = cam.getBBox(); const m = 70; const scale = 2;
    const copy = svg.cloneNode(true);
    copy.setAttribute("xmlns", SVGNS);
    copy.setAttribute("viewBox", `${b.x - m} ${b.y - m} ${b.width + m * 2} ${b.height + m * 2}`);
    copy.setAttribute("width", b.width + m * 2);
    copy.setAttribute("height", b.height + m * 2);
    copy.querySelector("#tree-cam").setAttribute("transform", "");
    const style = document.createElementNS(SVGNS, "style");
    style.textContent = `text{font-family:Segoe UI,Arial,sans-serif}.label{font-size:13px;fill:${tok("--text")}}
      .label,.caption{paint-order:stroke;stroke:${tok("--bg")};stroke-width:3px;stroke-linejoin:round}
      .label.big{font-size:15px;font-weight:600}.caption{font-size:12px;fill:${tok("--text-2")}}
      .counter{font-size:11px;fill:${tok("--on-color")};font-weight:700}.link{fill:none}.hit{fill:transparent}`;
    copy.insertBefore(style, copy.firstChild);
    const xml = new XMLSerializer().serializeToString(copy);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = (b.width + m * 2) * scale; c.height = (b.height + m * 2) * scale;
      const cx = c.getContext("2d");
      cx.fillStyle = tok("--bg"); cx.fillRect(0, 0, c.width, c.height);
      cx.drawImage(img, 0, 0, c.width, c.height);
      const a = document.createElement("a");
      a.download = `${t("tree.png_file")}-${new Date().toISOString().slice(0, 10)}.png`;
      a.href = c.toDataURL("image/png");
      a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  };

  // ── data ──────────────────────────────────────────────────────────────────
  async function load(keepView) {
    try {
      DATA = await ctx.api("/api/orgtree");
    } catch (e) {
      q("#tree-loading").hidden = false;
      q("#tree-loading").textContent = t("err.load", { msg: e.message });
      return;
    }
    const s = DATA.stats;
    q("#tree-stats").innerHTML = `<b>${s.projects}</b> ${esc(tn("tree.s_projects", s.projects, { n: "" }).trim())} · <b>${s.open}</b> ${esc(tn("tree.s_open", s.open, { n: "" }).trim())} · <b>${s.in_progress}</b> ${esc(t("tree.s_working"))} · <b>${s.mine}</b> ${esc(t("tree.s_yours"))}
      <span class="opt">· <b>${s.overdue}</b> ${esc(t("tree.s_overdue"))} · <b>${s.blocked}</b> ${esc(t("tree.s_blocked"))}</span>`;
    ctx.setSub(tn("tree.s_projects", s.projects));
    q("#tree-foot").textContent = t("tree.data_from", { when: ctx.fmtStamp(DATA.generated) });
    if (!keepView) COLLAPSED = keysFrom(2); // start: projects and roles, tasks folded away
    draw();
    if (!keepView) fit();
  }
  const onResize = () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (DATA) { draw(); fit(); } }, 150); };
  const onTheme = () => { if (DATA) draw(); };
  const mq = matchMedia("(prefers-color-scheme: dark)");
  addEventListener("resize", onResize);
  addEventListener("agentos-theme", onTheme);
  mq.addEventListener("change", onTheme);
  load(false);
  refreshTimer = setInterval(() => { if (document.visibilityState === "visible") load(true); }, 120000);

  return {
    reload: () => load(true),
    key: (k) => { if (k === "f") fit(); if (k === "u") switchLayout(); },
    destroy: () => {
      clearInterval(refreshTimer); clearTimeout(resizeTimer);
      removeEventListener("resize", onResize);
      removeEventListener("agentos-theme", onTheme);
      mq.removeEventListener("change", onTheme);
      hideTip();
    },
  };
}
