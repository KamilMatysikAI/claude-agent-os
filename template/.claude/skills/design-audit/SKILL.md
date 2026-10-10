---
name: design-audit
description: Visual audit of a web page at 7 screen widths (360–1920 px) — screenshots plus heuristics for horizontal scrolling, touch targets, visible focus, WCAG contrast, meta viewport, tiny text, missing alt/lang. Can inject a CSS file to preview a fix without touching production. Use for "check how the page looks on mobile", "design audit", "test responsiveness", "check contrast", "does the landing page work on a phone", and after any larger change to a page, widget or panel before reporting it works.
argument-hint: "<url> [--breakpoints 360,768] [--css-file fix.css]"
allowed-tools: ["Read", "Bash", "Glob"]
---

# /design-audit — verify the page in the render, not in the code

Implements optional rule W1 (`.claude/rules-optional/web.md`). Code can look right while the page looks wrong. What counts is what a visitor sees, on a phone too. One command gives a full set of screenshots and a list of concrete fixes.

## Run

```
python .claude/skills/design-audit/scripts/design_audit.py <url> [options]
```

Examples:

```
# full audit, 7 widths, full-page screenshots
python .claude/skills/design-audit/scripts/design_audit.py https://example.com/landing --slug landing

# quick mobile check, first screen only
python .claude/skills/design-audit/scripts/design_audit.py https://example.com --breakpoints 360,768 --viewport-only

# preview a CSS fix on the live page without deploying it
python .claude/skills/design-audit/scripts/design_audit.py https://example.com --css-file fix.css
```

**One URL per call.** For several pages, loop over them one call at a time; a single long run is harder to diagnose when it hangs.

### Options

| Flag | Meaning |
|---|---|
| `--out DIR` | output directory (default `notes/design-audit/YYYY-MM-DD/` in the workspace) |
| `--slug NAME` | file name stem (default from the URL) |
| `--breakpoints 360,768,1280` | custom widths (default 360/480/768/1024/1280/1600/1920) |
| `--wait 1200` | extra ms after load (animations, late JS) |
| `--viewport-only` | screenshot only the first screen |
| `--headed` | show the browser window |
| `--storage-state FILE` | Playwright storage-state JSON with cookies, for pages behind a login |
| `--css-file FILE` | inject CSS before measuring: a measured preview of a fix, production untouched |
| `--no-consent` | do not click consent banners (by default the audit accepts them and measures the page behind) |
| `--no-focus` / `--no-contrast` / `--no-touch` | switch off one heuristic |
| `--static` | force the static HTML check |
| `--timeout 300` | seconds per URL |

## Requirements and graceful degradation

The full audit needs **Playwright for Python** (optional, not installed with the workspace):

```
pip install playwright
python -m playwright install chromium
```

Install it into the same Python environment the workspace uses. Without it, or when the browser cannot start, the script falls back to a **static check** of the raw HTML (HTTP status, meta viewport, blocked zoom, `lang`, images without `alt`, inline CSS that kills the focus outline). The report then starts with a "STATIC MODE" note and the script exits with code **3**. Tell the owner the result is partial and give the install command; never present a static result as a full audit.

If Bash is refused or unavailable (the queue's `safe` profile has no Bash), you cannot run the audit: block the task with a human task "run the design audit" or ask the owner to run the command, and say so in the report.

## Output

In the output directory:
- `report-HHMMSS.md` — findings grouped Critical / Should fix / Minor, each with selector, element text and the widths where it occurs;
- `findings-HHMMSS.json` — the same, machine-readable (compare before/after a fix);
- `screenshots/HHMMSS/<slug>-<width>.png` — the screenshots.

Nothing is overwritten; every run has its own timestamp.

## Heuristics

| Rule | What it detects | Severity |
|---|---|---|
| `overflow-x` | document wider than the window, plus the outermost elements sticking out | Critical |
| `touch-target` | buttons/fields under 44×44 px at widths ≤ 1024 px; under 24×24 px is a hard WCAG 2.2 failure | Critical / Should fix |
| `touch-target-inline` | bare text link with a small height on a phone | Minor |
| `focus-outline-removed` | CSS rules with `:focus { outline: none }` and no replacement (shadow, border, background) | Critical |
| `focus-invisible` | element whose styles do not change on `focus()` — confirm on the screenshot | Should fix |
| `contrast` | text contrast under 4.5:1 (large text 3:1), with real alpha compositing | Critical / Should fix |
| `viewport-meta` / `viewport-zoom-blocked` | missing meta viewport, or zoom blocked | Critical / Should fix |
| `tiny-font`, `img-alt`, `html-lang` | text under 12 px, images without `alt`, no `lang` | Minor |

## Read before reporting a result

- **HTTP ≥ 400 is reported as an error.** An audit of a 404 page looks like a normal audit. Check the report header first.
- **No results is a tool failure, not a clean page.** The report says so explicitly.
- **Contrast is only measured on solid backgrounds.** Gradient or image behind text = no result (fewer false alarms); look at the screenshot.
- **Shadow DOM and iframes are out of reach.** Audit an embedded widget at its own URL.
- **A black rectangle where an embedded video should be in a full-page screenshot is a rendering artefact**: browsers do not paint cross-origin frames that were never in view. Scroll to it and check before reporting "the video is broken".
- **`focus-invisible` is a signal, not a verdict.** Programmatic `focus()` does not always trigger `:focus-visible`. Confirm on the screenshot.
- **Touch targets are checked only up to 1024 px.** A 24 px link on a desktop with a mouse is not a defect.
- **Consent banners** are accepted automatically for common consent managers and common button texts in several languages; a large fixed overlay that remains is noted in the report.
- The script deletes nothing.

## When the page belongs to someone else

Auditing is read-only and always allowed. A fix for a site maintained outside this workspace is prepared as a CSS file plus a description, measured with `--css-file`, and handed to the owner for approval. It is never deployed from here (rule 15).
