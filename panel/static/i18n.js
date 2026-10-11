// Panel language: one dictionary per language (i18n.<lang>.json), English as the fallback.
// The default comes from `language` in agentos.toml (/api/meta); the PL/EN switch is
// remembered in localStorage. Plurals use Intl.PluralRules (Polish has one/few/many),
// dates and numbers use Intl with the matching locale.

export const LANGS = ["en", "pl"];
const LOCALE = { en: "en-GB", pl: "pl-PL" };
const LS_KEY = "agentos.lang";

let lang = "en";
let dict = {};
let fallback = {};
const cache = {};

async function fetchDict(l) {
  if (cache[l]) return cache[l];
  const res = await fetch(`/i18n.${l}.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`dictionary ${l}: HTTP ${res.status}`);
  cache[l] = await res.json();
  return cache[l];
}

function stored() {
  try { return localStorage.getItem(LS_KEY); } catch (_) { return null; }
}

/** Pick the language: ?lang= in the URL, then the saved switch, then the workspace default. */
export async function initI18n(workspaceDefault) {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  const want = [fromUrl, stored(), workspaceDefault].find((l) => LANGS.includes(l)) || "en";
  await setLang(want, false);
}

export async function setLang(l, remember = true) {
  if (!LANGS.includes(l)) l = "en";
  fallback = await fetchDict("en");
  try {
    dict = l === "en" ? fallback : await fetchDict(l);
  } catch (_) {
    dict = fallback; l = "en";
  }
  lang = l;
  document.documentElement.lang = l;
  if (remember) { try { localStorage.setItem(LS_KEY, l); } catch (_) { /* private mode */ } }
  applyStatic();
  return l;
}

export const getLang = () => lang;
export const locale = () => LOCALE[lang] || "en-GB";
export const has = (key) => key in dict || key in fallback;

function interp(s, vars) {
  return String(s).replace(/\{(\w+)\}/g, (m, k) => (vars && k in vars ? String(vars[k]) : m));
}

/** Translate a key. Missing keys show the key itself, so a gap is visible, never silent. */
export function t(key, vars = {}) {
  let s = key in dict ? dict[key] : fallback[key];
  if (s == null) return key;
  if (typeof s === "object") s = s.other;
  return interp(s, vars);
}

/** Plural: the entry is {one, few, many, other}; {n} is the formatted number. */
export function tn(key, n, vars = {}) {
  const e = key in dict ? dict[key] : fallback[key];
  if (e == null) return `${n} ${key}`;
  const forms = typeof e === "object" ? e : { other: e };
  const cat = new Intl.PluralRules(locale()).select(n);
  const s = forms[cat] ?? forms.other;
  return interp(s, { n: fmtNum(n), ...vars });
}

export const fmtNum = (n) => new Intl.NumberFormat(locale()).format(n);

/** Join a list with commas and "and" / "i" (Intl.ListFormat). */
export function joinList(items) {
  try { return new Intl.ListFormat(locale(), { style: "long", type: "conjunction" }).format(items); }
  catch (_) { return items.join(", "); }
}

/** Static texts in the HTML: data-i18n="key" (text) and data-i18n-attr="attr:key;attr:key". */
export function applyStatic(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll("[data-i18n-attr]").forEach((el) => {
    el.dataset.i18nAttr.split(";").forEach((pair) => {
      const [attr, key] = pair.split(":");
      if (attr && key) el.setAttribute(attr.trim(), t(key.trim()));
    });
  });
}

// ── dates ───────────────────────────────────────────────────────────────────
export function parseDay(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
}

/** "Sun 11 Oct" / "niedz. 11.10"; long: "Sunday 11 October" / "niedziela 11.10". */
export function fmtDay(iso, long = false) {
  const d = parseDay(iso);
  if (!d) return "";
  if (lang === "pl") {
    const wd = new Intl.DateTimeFormat("pl-PL", { weekday: long ? "long" : "short" }).format(d);
    const dm = new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "2-digit" }).format(d);
    return `${wd} ${dm}`;
  }
  return new Intl.DateTimeFormat("en-GB", { weekday: long ? "long" : "short", day: "numeric", month: long ? "long" : "short" })
    .format(d).replace(",", "");
}

/** "11 Oct 2026" / "11.10.2026" for facts in the task detail. */
export function fmtDate(iso) {
  const d = parseDay(iso);
  if (!d) return "";
  return new Intl.DateTimeFormat(locale(), lang === "pl" ? { day: "2-digit", month: "2-digit", year: "numeric" }
    : { day: "numeric", month: "short", year: "numeric" }).format(d);
}
