#!/usr/bin/env python3
"""design-audit — visual audit of a web page at several screen widths.

For each URL and each breakpoint (default 360/480/768/1024/1280/1600/1920 px):
a screenshot plus heuristics run inside the page (horizontal overflow, touch
targets, visible focus, WCAG contrast, meta viewport, tiny text, missing alt/lang).
Output: a Markdown report, a findings JSON, and the screenshots.

Engine: Playwright for Python (optional dependency).
    pip install playwright
    python -m playwright install chromium

Without Playwright (or without an installed browser) the script degrades to a
static check of the raw HTML: HTTP status, meta viewport, zoom blocking, lang,
images without alt, inline CSS that removes the focus outline. No rendering, no
screenshots, no contrast; the report says so in its first lines. Exit code 3
signals that degraded mode was used.

Usage:
    python design_audit.py <url> [<url> ...] [--out DIR] [--slug NAME]
        [--breakpoints 360,768,1280] [--wait 1200] [--viewport-only]
        [--headed] [--storage-state FILE] [--css-file FILE] [--no-consent]
        [--no-focus] [--no-contrast] [--no-touch] [--timeout 300] [--static]

Fail-safe: one failing breakpoint does not stop the URL, one failing URL does
not stop the run. Nothing is ever deleted; every run writes new, timestamped
files next to older ones. No side effects at import time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html.parser
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE_FILE = HERE / "probe.js"

DEFAULT_BREAKPOINTS = [360, 480, 768, 1024, 1280, 1600, 1920]
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_LABEL = {"high": "Critical", "medium": "Should fix", "low": "Minor"}
INSTALL_HINT = "pip install playwright && python -m playwright install chromium"

RULE_NAMES = {
    "overflow-x": "horizontal scrolling",
    "overflow-x-element": "element outside the screen",
    "touch-target": "touch target too small",
    "touch-target-inline": "small text link",
    "focus-outline-removed": "CSS removes focus outline",
    "focus-invisible": "focus without visible change",
    "contrast": "WCAG contrast",
    "viewport-meta": "meta viewport",
    "viewport-zoom-blocked": "zoom blocked",
    "html-lang": "missing lang",
    "img-alt": "images without alt",
    "tiny-font": "text too small",
}

# Accept buttons of common consent managers. A consent banner covers the page,
# and an audit that measures the banner instead of the page is worthless.
CONSENT_JS = r"""(() => {
  const SEL = [
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "#onetrust-accept-btn-handler",
    ".cmplz-accept", ".cc-allow", ".cky-btn-accept",
    "[data-cky-tag=accept-button]", "#didomi-notice-agree-button", ".fc-cta-consent"
  ];
  for (const s of SEL) {
    const el = document.querySelector(s);
    if (el && el.offsetParent !== null) { el.click(); return s; }
  }
  const rx = /^(accept( all)?|allow all|agree|i agree|got it|ok|akzeptieren|alle akzeptieren|accepter|tout accepter|aceptar|accetta|akceptuj|zgadzam)/i;
  const btns = Array.prototype.slice.call(document.querySelectorAll("button, a[role=button], input[type=button]"), 0, 300);
  for (const b of btns) {
    const t = (b.innerText || b.value || "").trim();
    if (t && t.length < 40 && rx.test(t) && b.offsetParent !== null) { b.click(); return t; }
  }
  return "";
})()"""

# A fixed layer covering most of the screen means the results describe that layer.
OVERLAY_JS = r"""(() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  for (const el of Array.prototype.slice.call(document.querySelectorAll("body *"), 0, 3000)) {
    const cs = getComputedStyle(el);
    if (cs.position !== "fixed" && cs.position !== "sticky") continue;
    if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity || "1") < 0.3) continue;
    if ((parseInt(cs.zIndex, 10) || 0) < 100) continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height > vw * vh * 0.45) return (el.id || el.className || el.tagName).toString().slice(0, 60);
  }
  return "";
})()"""


# ---------------------------------------------------------------- helpers

def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"https?://", "", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text or "page")[:60]


def find_workspace(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "agentos.toml").is_file():
            return candidate
    return current


def probe_options(args) -> dict:
    return {
        "checkTouchTargets": not args.no_touch,
        "checkFocus": not args.no_focus,
        "checkContrast": not args.no_contrast,
        "checkTinyFont": True,
        "checkMeta": True,
        "maxFindings": 400,
        "maxFocusChecks": 60,
        "maxContrast": 60,
        "maxNodes": 4000,
        "touchMaxWidth": 1024,
    }


def load_playwright():
    """Return sync_playwright or None when the optional dependency is missing."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: WPS433 (optional import)
    except ImportError:
        return None
    return sync_playwright


# ---------------------------------------------------------------- browser mode

def audit_url_browser(browser, url: str, args, shots_dir: Path, probe_expr: str) -> dict:
    slug = args.slug or slugify(url)
    results, shots, errors, notes = [], {}, [], []
    context_kwargs = {}
    if args.storage_state:
        context_kwargs["storage_state"] = args.storage_state
    context = browser.new_context(**context_kwargs)
    try:
        page = context.new_page()
        page.set_default_timeout(45000)
        for bp in args.breakpoints:
            try:
                page.set_viewport_size({"width": bp, "height": round(bp * 0.72) + 320})
                response = page.goto(url, wait_until="load", timeout=45000)
                status = response.status if response else 0
                if status >= 400:
                    errors.append(f"HTTP {status} at {bp} px — you are auditing an error page, not the content")
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass  # pages with long polling never go idle; carry on
                if args.wait > 0:
                    page.wait_for_timeout(args.wait)
                if not args.no_consent:
                    hit = page.evaluate(CONSENT_JS)
                    if hit:
                        notes.append(f"accepted a consent banner at {bp} px ({hit})")
                        page.wait_for_timeout(900)
                # smooth scrolling animates back to the top and the screenshot catches half a page
                page.evaluate("document.documentElement.style.scrollBehavior = 'auto'")
                if args.css_text:
                    page.add_style_tag(content=args.css_text)  # local preview, production untouched
                    page.wait_for_timeout(500)
                # lazy images and entry animations: scroll to the bottom and back
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(400)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(250)
                blocker = page.evaluate(OVERLAY_JS)
                if blocker:
                    notes.append(f"a layer covers the screen at {bp} px ({blocker}); results describe what is visible")
                result = page.evaluate(probe_expr)
                result["bp"] = bp
                results.append(result)
                shot = shots_dir / f"{slug}-{bp:04d}.png"
                page.screenshot(path=str(shot), full_page=not args.viewport_only)
                shots[bp] = shot
            except Exception as exc:  # one breakpoint never stops the others
                errors.append(f"{bp} px: {exc}")
    finally:
        context.close()
    return {"url": url, "slug": slug, "mode": "browser", "results": results, "shots": shots,
            "errors": errors, "notes": sorted(set(notes))}


# ---------------------------------------------------------------- static fallback

class _HeadScanner(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.viewport = None
        self.lang = None
        self.images = 0
        self.images_no_alt = 0
        self.in_style = False
        self.styles: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.lang = attrs.get("lang")
        elif tag == "meta" and (attrs.get("name") or "").lower() == "viewport":
            self.viewport = attrs.get("content") or ""
        elif tag == "img":
            self.images += 1
            if "alt" not in attrs:
                self.images_no_alt += 1
        elif tag == "style":
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)


def audit_url_static(url: str, args, reason: str) -> dict:
    slug = args.slug or slugify(url)
    findings, errors = [], []
    notes = [f"STATIC MODE ({reason}): raw HTML only — no rendering, no screenshots, no contrast, "
             f"no touch targets, no overflow. Full audit: {INSTALL_HINT}"]
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "design-audit/1.0 (static check)"})
        with urllib.request.urlopen(request, timeout=min(args.timeout, 60)) as response:
            body = response.read(3_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
    except urllib.error.HTTPError as exc:
        errors.append(f"HTTP {exc.code} — you are auditing an error page, not the content")
        body = exc.read(3_000_000).decode("utf-8", "replace") if exc.fp else ""
    except Exception as exc:
        errors.append(f"fetch failed: {exc}")
        body = ""
    if body:
        scanner = _HeadScanner()
        try:
            scanner.feed(body)
        except Exception as exc:
            errors.append(f"HTML parse: {exc}")
        if scanner.viewport is None:
            findings.append({"rule": "viewport-meta", "severity": "high",
                             "msg": 'Missing <meta name="viewport"> — the page will not scale on phones'})
        else:
            content = scanner.viewport.lower()
            if "user-scalable=no" in content or re.search(r"maximum-scale\s*=\s*1(\.0)?\b", content):
                findings.append({"rule": "viewport-zoom-blocked", "severity": "medium",
                                 "msg": "Meta viewport blocks zooming", "detail": content})
        if not scanner.lang:
            findings.append({"rule": "html-lang", "severity": "low", "msg": "No lang attribute on <html>"})
        if scanner.images_no_alt:
            findings.append({"rule": "img-alt", "severity": "low",
                             "msg": f"{scanner.images_no_alt} of {scanner.images} image(s) without an alt attribute"})
        css = "\n".join(scanner.styles)
        killed = re.findall(r"([^{}]*:focus[^{}]*)\{[^}]*outline\s*:\s*(?:none|0)[^}]*\}", css)
        if killed:
            findings.append({"rule": "focus-outline-removed", "severity": "high",
                             "msg": f"Inline CSS removes the focus outline in {len(killed)} rule(s); check for a replacement",
                             "detail": " | ".join(s.strip()[:80] for s in killed[:5])})
    result = {"bp": None, "findings": findings, "docHeight": None}
    return {"url": url, "slug": slug, "mode": "static", "results": [result], "shots": {},
            "errors": errors, "notes": notes}


# ---------------------------------------------------------------- report

def merge_findings(results: list[dict]) -> list[dict]:
    """The same issue at several widths becomes one entry with a list of widths."""
    merged: dict = {}
    for res in results:
        bp = res.get("bp")
        for finding in res.get("findings", []):
            key = (finding.get("rule"), finding.get("selector", ""), re.sub(r"\d+", "#", finding.get("msg", "")))
            entry = merged.get(key)
            if entry is None:
                entry = dict(finding, breakpoints=[], examples=[])
                merged[key] = entry
            if bp is not None:
                entry["breakpoints"].append(bp)
            if finding.get("msg") not in entry["examples"]:
                entry["examples"].append(finding.get("msg"))
            if SEVERITY_ORDER.get(finding.get("severity"), 3) < SEVERITY_ORDER.get(entry.get("severity"), 3):
                entry["severity"] = finding["severity"]
    out = list(merged.values())
    out.sort(key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 3), f.get("rule", ""), -len(f["breakpoints"])))
    return out


def render_report(audits: list[dict], out_dir: Path, stamp: dt.datetime) -> str:
    lines = [f"# Design audit — {stamp:%Y-%m-%d %H:%M}", ""]
    for audit in audits:
        merged = merge_findings(audit["results"])
        counts = {sev: sum(1 for f in merged if f.get("severity") == sev) for sev in SEVERITY_ORDER}
        lines += [f"## {audit['url']}", ""]
        widths = [str(r.get("bp")) for r in audit["results"] if r.get("bp") is not None]
        lines.append(f"Mode: {audit['mode']} · widths: {', '.join(widths) or 'n/a'} px · "
                     f"critical {counts['high']} · should fix {counts['medium']} · minor {counts['low']}")
        lines.append("")
        for note in audit.get("notes", [])[:6]:
            lines.append(f"> {note}")
        if audit.get("errors"):
            lines.append(f"> Run errors: {'; '.join(audit['errors'][:5])}")
        if audit.get("notes") or audit.get("errors"):
            lines.append("")
        if not merged:
            if audit["results"] and not audit.get("errors"):
                lines += ["Clean: no heuristic fired.", ""]
            else:
                lines += ["No results. Treat this as a tool failure, not as a clean page.", ""]
        for sev in ("high", "medium", "low"):
            group = [f for f in merged if f.get("severity") == sev]
            if not group:
                continue
            lines += [f"### {SEVERITY_LABEL[sev]} ({len(group)})", ""]
            for finding in group:
                rule = RULE_NAMES.get(finding.get("rule"), finding.get("rule"))
                lines.append(f"- **{rule}** — {finding['examples'][0]}")
                meta = []
                if finding.get("selector"):
                    meta.append(f"`{finding['selector']}`")
                if finding.get("text"):
                    meta.append(f'"{finding["text"]}"')
                if finding.get("detail"):
                    meta.append(finding["detail"])
                bps = sorted(set(finding["breakpoints"]))
                if bps:
                    meta.append("widths: " + ", ".join(str(b) for b in bps) + " px")
                if meta:
                    lines.append("  <br>" + " · ".join(meta))
            lines.append("")
        if audit["shots"]:
            lines += ["### Screenshots", "", "| Width | Document height | File |", "|---|---|---|"]
            heights = {r.get("bp"): r.get("docHeight") for r in audit["results"]}
            for bp in sorted(audit["shots"]):
                rel = audit["shots"][bp].relative_to(out_dir).as_posix()
                lines.append(f"| {bp} px | {heights.get(bp, '?')} px | [{Path(rel).name}]({rel}) |")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def parse_args(argv):
    ap = argparse.ArgumentParser(description="Visual audit of web pages at several widths.")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--out", help="output directory (default: <workspace>/notes/design-audit/YYYY-MM-DD)")
    ap.add_argument("--slug", help="file name stem (only used with a single URL)")
    ap.add_argument("--breakpoints", default=",".join(str(b) for b in DEFAULT_BREAKPOINTS))
    ap.add_argument("--wait", type=int, default=1200, help="extra ms to wait after load")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per URL (static fetch uses up to 60)")
    ap.add_argument("--viewport-only", action="store_true", help="screenshot the first screen instead of the full page")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--storage-state", help="Playwright storage state JSON (cookies) for pages behind a login")
    ap.add_argument("--css-file", help="CSS injected before measuring: preview a fix without touching production")
    ap.add_argument("--no-consent", action="store_true", help="do not click consent banners")
    ap.add_argument("--no-focus", action="store_true")
    ap.add_argument("--no-contrast", action="store_true")
    ap.add_argument("--no-touch", action="store_true")
    ap.add_argument("--static", action="store_true", help="force the static HTML check (no browser)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    args.breakpoints = [int(b) for b in str(args.breakpoints).split(",") if b.strip()]
    args.css_text = Path(args.css_file).read_text(encoding="utf-8") if args.css_file else ""
    if args.slug and len(args.urls) > 1:
        args.slug = None  # one slug for several URLs would overwrite files

    stamp = dt.datetime.now()
    out_dir = Path(args.out) if args.out else find_workspace(Path.cwd()) / "notes" / "design-audit" / f"{stamp:%Y-%m-%d}"
    out_dir = out_dir.resolve()
    shots_dir = out_dir / "screenshots" / f"{stamp:%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"design-audit -> {out_dir}")

    sync_playwright = None if args.static else load_playwright()
    static_reason = "forced with --static" if args.static else ""
    if sync_playwright is None and not args.static:
        static_reason = "Playwright not installed"
        print(f"  Playwright not installed — static check only. For the full audit: {INSTALL_HINT}")

    audits: list[dict] = []
    if sync_playwright is not None:
        try:
            shots_dir.mkdir(parents=True, exist_ok=True)
            probe_expr = PROBE_FILE.read_text(encoding="utf-8").replace("__OPTS__", json.dumps(probe_options(args)))
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not args.headed)
                try:
                    for url in args.urls:
                        started = time.monotonic()
                        print(f"  -> {url} ({len(args.breakpoints)} widths)")
                        try:
                            audits.append(audit_url_browser(browser, url, args, shots_dir, probe_expr))
                        except Exception as exc:  # one URL never stops the run
                            audits.append({"url": url, "slug": slugify(url), "mode": "browser", "results": [],
                                           "shots": {}, "errors": [str(exc)], "notes": []})
                        print(f"     done in {time.monotonic() - started:.0f} s")
                finally:
                    browser.close()
        except Exception as exc:
            # typically: browser binaries not installed ("Executable doesn't exist")
            static_reason = f"browser could not start: {str(exc).splitlines()[0][:160]}"
            print(f"  {static_reason}\n  Try: python -m playwright install chromium")
            done = {a["url"] for a in audits}
            audits += [audit_url_static(u, args, static_reason) for u in args.urls if u not in done]
    else:
        audits = [audit_url_static(url, args, static_reason) for url in args.urls]

    suffix = f"{stamp:%H%M%S}"
    report_path = out_dir / f"report-{suffix}.md"
    json_path = out_dir / f"findings-{suffix}.json"
    report_path.write_text(render_report(audits, out_dir, stamp), encoding="utf-8")
    json_path.write_text(json.dumps({
        "generated": stamp.isoformat(timespec="seconds"),
        "breakpoints": args.breakpoints,
        "audits": [{
            "url": a["url"], "slug": a["slug"], "mode": a["mode"], "errors": a["errors"], "notes": a["notes"],
            "findings": merge_findings(a["results"]),
            "screenshots": {str(bp): p.relative_to(out_dir).as_posix() for bp, p in a["shots"].items()},
        } for a in audits],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    for audit in audits:
        merged = merge_findings(audit["results"])
        high = sum(1 for f in merged if f.get("severity") == "high")
        print(f"  {audit['slug']} [{audit['mode']}] — {len(merged)} findings ({high} critical), "
              f"{len(audit['shots'])} screenshots" + (f", {len(audit['errors'])} errors" if audit["errors"] else ""))
    print(f"report: {report_path}")
    print(f"json:   {json_path}")
    return 3 if any(a["mode"] == "static" for a in audits) else 0


if __name__ == "__main__":
    sys.exit(main())
