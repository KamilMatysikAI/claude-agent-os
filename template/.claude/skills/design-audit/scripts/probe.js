/* design-audit probe — runs INSIDE the page via page.evaluate().
 *
 * The file is ONE expression (an IIFE) passed to evaluate() as a string.
 * The runner (design_audit.py) replaces the __OPTS__ placeholder with a JSON object.
 * Every heuristic is wrapped so that one failing check never stops the others.
 */
(() => {
  const OPTS = __OPTS__;
  const findings = [];
  const MAX_NODES = OPTS.maxNodes || 4000;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const add = (rule, severity, msg, extra) => {
    if (findings.length >= (OPTS.maxFindings || 400)) return;
    findings.push(Object.assign({ rule, severity, msg }, extra || {}));
  };

  // ---------- helpers ----------

  function cssPath(el) {
    if (!el || el.nodeType !== 1) return "";
    const parts = [];
    let node = el;
    let depth = 0;
    while (node && node.nodeType === 1 && depth < 4) {
      let seg = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift(seg + "#" + node.id);
        break;
      }
      const cls = (node.getAttribute("class") || "")
        .split(/\s+/)
        .filter((c) => c && !/^(is-|has-|js-)/.test(c) && c.length < 30)
        .slice(0, 2);
      if (cls.length) seg += "." + cls.join(".");
      parts.unshift(seg);
      node = node.parentElement;
      depth++;
    }
    return parts.join(" > ");
  }

  function label(el) {
    const t = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
    if (t) return t.slice(0, 60);
    const a = el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("alt"));
    return a ? String(a).slice(0, 60) : "";
  }

  function box(el) {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left + window.scrollX), y: Math.round(r.top + window.scrollY), w: Math.round(r.width), h: Math.round(r.height) };
  }

  function visible(el, cs) {
    cs = cs || getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    if (parseFloat(cs.opacity || "1") < 0.05) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  }

  function parseColor(str) {
    if (!str) return null;
    // color-mix() and relative colours come back as "color(srgb r g b / a)" with 0–1 channels.
    // Without this branch such a background reads as transparent and yields a false 1:1 contrast.
    const cm = str.match(/color\(srgb\s+([^)]+)\)/);
    if (cm) {
      const q = cm[1].split(/[\s/]+/).filter((x) => x !== "");
      if (q.length < 3) return null;
      return { r: parseFloat(q[0]) * 255, g: parseFloat(q[1]) * 255, b: parseFloat(q[2]) * 255, a: q.length > 3 ? parseFloat(q[3]) : 1 };
    }
    const m = str.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter((x) => x !== "");
    if (p.length < 3) return null;
    return { r: parseFloat(p[0]), g: parseFloat(p[1]), b: parseFloat(p[2]), a: p.length > 3 ? parseFloat(p[3]) : 1 };
  }

  function over(top, bottom) {
    const a = top.a;
    return { r: top.r * a + bottom.r * (1 - a), g: top.g * a + bottom.g * (1 - a), b: top.b * a + bottom.b * (1 - a), a: 1 };
  }

  // Effective background: climb until an opaque layer. Gradient or image => null (no guessing).
  function effectiveBg(el) {
    let node = el;
    const layers = [];
    let guard = 0;
    while (node && node.nodeType === 1 && guard++ < 30) {
      const cs = getComputedStyle(node);
      if (cs.backgroundImage && cs.backgroundImage !== "none") return null;
      const c = parseColor(cs.backgroundColor);
      if (c && c.a > 0.001) {
        layers.push(c);
        if (c.a >= 0.999) break;
      }
      node = node.parentElement;
    }
    let acc = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i--) acc = over(layers[i], acc);
    return acc;
  }

  function lum(c) {
    const f = (v) => {
      v = v / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }

  function contrast(a, b) {
    const l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  }

  function directText(el) {
    let t = "";
    for (let i = 0; i < el.childNodes.length; i++) {
      const n = el.childNodes[i];
      if (n.nodeType === 3) t += n.nodeValue;
    }
    return t.replace(/\s+/g, " ").trim();
  }

  const SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, SVG: 1, PATH: 1, TEMPLATE: 1, OPTION: 1, HEAD: 1, META: 1, LINK: 1, TITLE: 1, BR: 1, IFRAME: 1 };
  const all = Array.prototype.slice.call(document.querySelectorAll("body *"), 0, MAX_NODES);

  // ---------- 1. horizontal overflow ----------
  const docW = Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0);
  try {
    if (docW > vw + 2) {
      add("overflow-x", "high", "Page scrolls horizontally: " + docW + " px in a " + vw + " px window", { detail: "excess " + (docW - vw) + " px" });
      const guilty = [];
      for (const el of all) {
        if (SKIP[el.tagName]) continue;
        const cs = getComputedStyle(el);
        if (!visible(el, cs)) continue;
        const r = el.getBoundingClientRect();
        const right = r.right + window.scrollX;
        if (right > vw + 2 && r.width > 4 && r.left + window.scrollX < docW) guilty.push({ el, right });
      }
      // keep only outermost elements; their children are the same problem
      guilty
        .filter((g) => !guilty.some((o) => o.el !== g.el && o.el.contains(g.el)))
        .sort((a, b) => b.right - a.right)
        .slice(0, 8)
        .forEach((g) => add("overflow-x-element", "medium", "Element sticks out past the right edge by " + Math.round(g.right - vw) + " px", { selector: cssPath(g.el), text: label(g.el), box: box(g.el) }));
    }
  } catch (e) {}

  // ---------- 2. touch targets (touch-sized viewports only) ----------
  try {
    if (OPTS.checkTouchTargets && vw <= (OPTS.touchMaxWidth || 1024)) {
      const SEL = 'a[href], button, input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="switch"], [onclick], [tabindex]:not([tabindex="-1"])';
      const nodes = Array.prototype.slice.call(document.querySelectorAll(SEL), 0, 400);
      const seen = {};
      for (const el of nodes) {
        const cs = getComputedStyle(el);
        if (!visible(el, cs) || el.disabled) continue;
        const r = el.getBoundingClientRect();
        if (r.width >= 44 && r.height >= 44) continue;
        // WCAG 2.2 exempts targets inside a sentence: a link within a paragraph is fine
        const p = el.parentElement;
        if (el.tagName === "A" && p && directText(p).length > 0) continue;
        const padded = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) >= 8 || parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) >= 16;
        const bg = parseColor(cs.backgroundColor);
        const bordered = parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderBottomWidth) > 0;
        const buttonish = el.tagName === "BUTTON" || el.tagName === "INPUT" || el.getAttribute("role") === "button" || cs.display.indexOf("inline") === -1 || padded || bordered || (bg && bg.a > 0.05);
        const key = cssPath(el) + "|" + Math.round(r.width) + "x" + Math.round(r.height);
        if (seen[key]) continue;
        seen[key] = 1;
        if (buttonish) {
          add("touch-target", Math.min(r.width, r.height) < 24 ? "high" : "medium", "Touch target " + Math.round(r.width) + "x" + Math.round(r.height) + " px (aim for 44x44; WCAG 2.2 hard minimum is 24x24)", { selector: cssPath(el), text: label(el), box: box(el) });
        } else if (vw <= 768) {
          add("touch-target-inline", "low", "Text link " + Math.round(r.height) + " px tall — hard to hit with a thumb", { selector: cssPath(el), text: label(el), box: box(el) });
        }
      }
    }
  } catch (e) {}

  // ---------- 3. focus ----------
  if (OPTS.checkFocus) {
    // 3a. CSS anti-pattern: :focus { outline: none } without a replacement
    try {
      let killed = 0;
      const samples = [];
      for (const sh of Array.prototype.slice.call(document.styleSheets)) {
        let rules = null;
        try { rules = sh.cssRules; } catch (e) { continue; } // cross-origin sheet
        if (!rules) continue;
        for (let i = 0; i < rules.length && i < 3000; i++) {
          const rule = rules[i];
          if (!rule.selectorText || rule.selectorText.indexOf(":focus") === -1 || !rule.style) continue;
          const st = rule.style;
          const o = [st.getPropertyValue("outline"), st.getPropertyValue("outline-width"), st.getPropertyValue("outline-style")].join(" ");
          if (!/none|0px|\b0\b/.test(o)) continue;
          const compensated = ["box-shadow", "border", "border-color", "background", "background-color"].some((p) => (st.getPropertyValue(p) || "").trim());
          if (compensated) continue;
          killed++;
          if (samples.length < 5) samples.push(rule.selectorText.slice(0, 80));
        }
      }
      if (killed) add("focus-outline-removed", "high", "CSS removes the focus outline in " + killed + " rule(s) without a replacement", { detail: samples.join(" | ") });
    } catch (e) {}

    // 3b. runtime: focus() and compare computed styles
    try {
      const FOC = 'a[href], button, input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])';
      const cands = Array.prototype.slice.call(document.querySelectorAll(FOC)).filter((el) => visible(el) && !el.disabled);
      const sx = window.scrollX, sy = window.scrollY;
      const active = document.activeElement;
      const snap = (cs) => [cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.boxShadow, cs.borderColor, cs.borderWidth, cs.backgroundColor, cs.color, cs.textDecorationLine].join("|");
      const seenSel = {};
      let checked = 0;
      for (const el of cands) {
        if (checked >= (OPTS.maxFocusChecks || 60)) break;
        const sel = cssPath(el);
        if (seenSel[sel]) continue; // one representative per pattern
        seenSel[sel] = 1;
        checked++;
        let before, after;
        try {
          before = snap(getComputedStyle(el));
          el.focus({ preventScroll: true });
          after = snap(getComputedStyle(el));
          el.blur();
        } catch (e) { continue; }
        if (before === after) add("focus-invisible", "medium", "No visible style change on focus (confirm on a screenshot)", { selector: sel, text: label(el), box: box(el) });
      }
      try { if (active && active.focus) active.focus({ preventScroll: true }); } catch (e) {}
      window.scrollTo(sx, sy);
    } catch (e) {}
  }

  // ---------- 4. WCAG contrast ----------
  try {
    if (OPTS.checkContrast) {
      const seen = {};
      let count = 0;
      for (const el of all) {
        if (count >= (OPTS.maxContrast || 60)) break;
        if (SKIP[el.tagName]) continue;
        const txt = directText(el);
        if (txt.length < 2) continue;
        const cs = getComputedStyle(el);
        if (!visible(el, cs)) continue;
        const fgRaw = parseColor(cs.color);
        if (!fgRaw) continue;
        const bg = effectiveBg(el);
        if (!bg) continue; // gradient or image behind the text: no guessing
        const fg = fgRaw.a >= 0.999 ? fgRaw : over(fgRaw, bg);
        const size = parseFloat(cs.fontSize) || 16;
        const weight = parseInt(cs.fontWeight, 10) || 400;
        const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3.0 : 4.5;
        const ratio = contrast(fg, bg);
        if (ratio >= need) continue;
        const key = cs.color + "|" + Math.round(bg.r) + "," + Math.round(bg.g) + "," + Math.round(bg.b) + "|" + Math.round(size);
        if (seen[key]) continue;
        seen[key] = 1;
        count++;
        const hex = (c) => "#" + [c.r, c.g, c.b].map((v) => ("0" + Math.round(v).toString(16)).slice(-2)).join("");
        add("contrast", ratio < need - 1.5 ? "high" : "medium", "Contrast " + ratio.toFixed(2) + ":1, needs " + need + ":1 (" + Math.round(size) + " px" + (weight >= 700 ? ", bold" : "") + ")", { selector: cssPath(el), text: txt.slice(0, 60), detail: "text " + hex(fg) + " on " + hex(bg), box: box(el) });
      }
    }
  } catch (e) {}

  // ---------- 5. page-level basics ----------
  try {
    if (OPTS.checkMeta) {
      const mv = document.querySelector('meta[name="viewport"]');
      if (!mv) {
        add("viewport-meta", "high", 'Missing <meta name="viewport"> — the page will not scale on phones');
      } else {
        const c = (mv.getAttribute("content") || "").toLowerCase();
        if (c.indexOf("user-scalable=no") !== -1 || /maximum-scale\s*=\s*1(\.0)?\b/.test(c)) add("viewport-zoom-blocked", "medium", "Meta viewport blocks zooming", { detail: c });
      }
      if (!document.documentElement.getAttribute("lang")) add("html-lang", "low", "No lang attribute on <html> (screen readers, hyphenation)");
      let noAlt = 0;
      for (const im of Array.prototype.slice.call(document.querySelectorAll("img"), 0, 200)) {
        if (!im.hasAttribute("alt") && visible(im)) noAlt++;
      }
      if (noAlt) add("img-alt", "low", noAlt + " image(s) without an alt attribute");
    }
  } catch (e) {}

  try {
    if (OPTS.checkTinyFont) {
      const seen = {};
      let tiny = 0;
      for (const el of all) {
        if (tiny >= 10) break;
        if (SKIP[el.tagName]) continue;
        const txt = directText(el);
        if (txt.length < 4) continue;
        const cs = getComputedStyle(el);
        if (!visible(el, cs)) continue;
        const size = parseFloat(cs.fontSize) || 16;
        if (size >= 12) continue;
        const key = cssPath(el) + "|" + size;
        if (seen[key]) continue;
        seen[key] = 1;
        tiny++;
        add("tiny-font", "low", "Text at " + size.toFixed(1) + " px (below 12 px is hard to read on phones)", { selector: cssPath(el), text: txt.slice(0, 60), box: box(el) });
      }
    }
  } catch (e) {}

  return {
    viewport: { w: vw, h: vh },
    docWidth: docW,
    docHeight: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),
    nodes: all.length,
    findings: findings,
  };
})()
