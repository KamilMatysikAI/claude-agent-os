# CONTRACT — shared interface for everyone building this repo

Working name: **claude-agent-os** (may be renamed before release — keep the name in ONE place: `agentos/__init__.py: PRODUCT_NAME`).
This repo is a public, generic, cross-platform package. It is built FROM a private system, but NOTHING private goes in.

## Hard rules for builders
1. Write only inside this repo and only in the directories you own (see "Ownership"). Never modify the private reference workspace (path given in your prompt) or any other path — read only, as reference.
2. No secrets, emails, phone numbers, personal names, company names, brand names, amounts, tax IDs, local paths (drive paths, usernames). Banned-words list: `tests/banned_words.txt` (CI fails on hit). Incidents used as rationale are anonymised ("a batch of emails failed because of one typo address", not who/where).
3. Do not copy third-party skills/plugins (marketing pack, seo-*, ui-ux-pro-max, frontend-design, superpowers, dev-browser, ffmpeg-skill, ai-writing-patterns, video-generator, meta-ads-analyzer). Link them in README only.
4. Language: everything in **English** (code, docs, templates, rules). README gets a short Polish section at the end (owned by docs).
5. Python ≥ 3.11, **stdlib only** (tomllib). Tests: pytest (dev dependency only).
6. Do not `git commit` — the coordinator commits. Do not create remotes, do not publish.
7. Cross-platform: Windows, macOS, Linux. Use `pathlib`, no hard-coded separators, no PowerShell/VBS required.

## Ownership
| Dir / file | Owner |
|---|---|
| `template/CLAUDE.md`, `template/.claude/agents/`, `template/.claude/rules/`, `template/projects/.templates/`, `template/inbox/`, `template/ideas/`, `demo/` | content |
| `template/.claude/skills/` | skills |
| `agentos/` (except `scheduler/`, `doctor.py`, `install` logic), `profiles/`, `tests/test_engine_*.py` | engine |
| `install.py`, `agentos/scheduler/`, `agentos/doctor.py`, `.github/`, `tests/test_install_*.py`, `tests/test_clean_*.py`, `tests/banned_words.txt`, `SECURITY.md` | installer |
| `panel/`, `tests/test_panel_*.py` | panel (later) |
| `README.md`, `LICENSE`, `docs/` | docs (later) |

## Workspace layout (what install.py creates in the USER's workspace from `template/`)
```
<workspace>/
  CLAUDE.md                     constitution with {{owner_name}} etc. placeholders filled by installer
  agentos.toml                  config (see below)
  .claude/agents/  ceo.md marketing.md copy.md web.md soft.md research.md
  .claude/rules/   01-work.md 02-security.md 03-automation.md 04-multi-agent.md 05-projects.md
                   persona.md soul.md context.md   (templates filled by /setup)
  .claude/rules-optional/  web.md sales.md   (NOT auto-loaded; installer/setup copies into .claude/rules/ only when the user opts in)
  .claude/skills/  setup new-project project agent-queue create-task end premortem reflect memory-update design-audit add-idea
  projects/
    .templates/    PROJECT.md PLAN.md LOG.md task-agent.md task-human.md task-decision.md task-review.md
    <slug>/PROJECT.md PLAN.md LOG.md tasks/ materials/
    dashboard.md   GENERATED — never edit by hand
  inbox/           ad-hoc tasks for the agent (queue scans it, like projects/*/tasks/A-*)
    done/
  ideas/
  TODO.md          human view; generated block between <!-- AGENTOS:START --> and <!-- AGENTOS:END -->
  .agentos/        runtime state: logs/, locks/, run-now.json, notified.json  (gitignored)
  .agentos/venv/   the engine, pip-installed by install.py (normal install; offline: a .pth link to the repo)
```

## Task file schema (`projects/<slug>/tasks/<ID>-<kebab-slug>.md`, inbox: `inbox/<kebab-slug>.md`)
IDs: `A-001` agent task, `H-001` human task. Next ID = max over the WHOLE project tasks dir (incl. archived) + 1.

```yaml
---
id: A-012
project: coffee-shop            # slug; empty for inbox
title: Draft landing page copy
owner: copy                     # ceo|marketing|copy|web|soft|research|human
type: task                      # task|decision|review
status: todo                    # todo|in_progress|blocked|done|cancelled
priority: normal                # high|normal|low
due: 2026-10-20                 # optional
created: 2026-10-10
closed:                         # set when done/cancelled
size: small                     # small|medium|large
autonomy: full                  # full|ask   (ask = queue skips, needs human)
source: local                   # local|panel|external  (external ⇒ forced safe profile)
profile:                        # optional override: safe|developer|full (cannot exceed config max)
blocked_by: []                  # list of task IDs
unblocked_by: H-004             # REQUIRED when status: blocked — the human task that unblocks
decision:                       # accepted|rejected (type: decision only)
evidence:                       # REQUIRED to set done: path, link or test result
lock:                           # "<ISO8601>|<host>|<pid>" while a run holds it
---
```
Sections (H2, in this order when present): `## Goal`, `## Context`, `## Steps` (checkboxes), `## Definition of done`, `## For approval` (decision: the recommendation the human accepts), `## Unblocking action` (blocked), `## Owner notes` (human comments; agents MUST read the latest one before acting/closing), `## Progress log` (agent appends one line per step: `- 2026-10-10 14:02 — ...`).

Rules enforced by engine (`guard`): blocked without `unblocked_by` → create human mini-task; accepted decision without an executing A-task → create one (due = accept + 2 days, quoting `## For approval`); WIP = count of A-* in todo|in_progress|blocked per project, limit `wip_limit` (default 5); done without `evidence` → flagged in dashboard.

PROJECT.md frontmatter: `slug, name, status (active|paused|done), owner_human, wip_limit, created`. Sections: Goal, Success criteria (measurable, with date), Constraints, Out of scope.

## Config `agentos.toml`
```toml
owner_name = "Alex"
language = "en"              # language agents write in for the user
timezone = "Europe/Warsaw"

[queue]
enabled = false              # installer asks
profile = "safe"             # safe|developer|full  (max allowed; external sources always safe)
interval_minutes = 30
timeout_minutes = 45
max_tasks_per_run = 1
claude_bin = "claude"
model = ""                   # empty = CLI default
cooldown_minutes = 0

[projects]
wip_limit = 5
human_task_max_minutes = 15

[notify]
kind = "none"                # none|file|telegram
digest_hours = [8, 15, 21]   # effects only, batched; failures go to log + one daily line
# telegram token/chat id ONLY from .env: AGENTOS_TELEGRAM_TOKEN, AGENTOS_TELEGRAM_CHAT_ID

[panel]
enabled = false
host = "127.0.0.1"
port = 8777
```

## CLI (single entry point, used by scheduler, panel and docs)
```
python -m agentos dashboard            # regenerate projects/dashboard.md + TODO.md block
python -m agentos guard                # guard rules above; idempotent
python -m agentos status [slug]
python -m agentos run [--task PATH] [--dry-run]   # queue: pick → lock → claude -p with profile → log → unlock
python -m agentos notify-digest
python -m agentos doctor
python -m agentos schedule install|remove|status
python -m agentos panel                # if panel installed
```
All commands take `--workspace PATH` (default: walk up from cwd to find `agentos.toml`).
Generated commands (tick.py, panel run-now, workspace CLAUDE.md and skills via the `{{engine}}` placeholder) run `<workspace>/.agentos/venv/{bin|Scripts}/python -P -m agentos`; `python -m agentos` from the repo folder stays the fallback (`--no-venv`). Path helpers: `agentos/env.py`.
Library API in `agentos/core.py` (engine owns; panel and installer import it): `load_config`, `find_workspace`, `iter_tasks`, `read_task`, `write_task_atomic`, `set_status(task, status, evidence=None)`, `decide(task, accepted: bool, note: str)`, `add_note`, `next_id`, `acquire_lock/release_lock`, `create_task(...)`.

## Profiles (`profiles/*.json`, passed via `--settings`; runner builds the full command)
- `safe` (default): `--allowedTools "Read,Glob,Grep,Edit,Write,WebSearch,WebFetch"`, deny Read/Edit/Write on `**/.env*`, `~/.ssh/**`, `~/.aws/**`, `**/credentials*`, `**/*.pem`, `**/*.key`; `--strict-mcp-config`; cwd = workspace; NO Bash, NO `--dangerously-skip-permissions`.
- `developer`: safe + allow `Bash(git status:*)`, `Bash(git diff:*)`, `Bash(git log:*)`, `Bash(python -m pytest:*)`, `Bash(npm test:*)`; deny `Bash(git push:*)`, `Bash(rm:*)`, `Bash(curl:*)`, `Bash(wget:*)`.
- `full`: `--dangerously-skip-permissions` + safe deny list; installer shows a warning and requires typing `I understand`.
Lesson to keep in comments: `--add-dir` widens access, `--allowedTools` narrows tools not paths; only `deny` rules in settings enforce file boundaries.

## Changelog
- coordinator: optional rules live in `template/.claude/rules-optional/` (Claude Code auto-loads everything under `.claude/rules/`, incl. subfolders). Installer `--rules web,sales` and `/setup` copy chosen files into `.claude/rules/`.
- coordinator: inbox tasks have empty `id:`; engine must accept that (identify inbox tasks by path).
- coordinator (from skills): workspace layout adds `notes/` (`notes/sessions/` for /end, premortem and design-audit reports), `.claude/rules/now.md` (memory-update), `ideas/index.md` (generated by add-idea), `.claude/rules-archive/` (setup archives replaced rule files here — outside auto-load), `.agentos/tmp/`. Installer creates `notes/` and `notes/sessions/`.
- coordinator: accepted decision = `status: done` + `decision: accepted` (rejected = `status: done` + `decision: rejected`). Interactive-session lock = `<ISO>|<host>|session`.
- coordinator → engine: add `python -m agentos next-id <slug|inbox> A|H` (counter shared across A- and H-, includes archived). Runner refreshes dashboard after every run (skills assume it; safe profile has no Bash).
- engine: done — `next-id` (shared A/H counter), session locks (`<ISO>|<host>|session`, same 90-min age rule; tz offsets converted to local), dashboard refresh after every run that executed a task, `decide()` = `status: done` + `decision: accepted|rejected` (+ auto `evidence` and an `## Owner notes` line).
- engine deviations/additions: (1) profiles also deny `Read/Edit/Write(.agentos/**)`-style access to queue state (`Edit`/`Write` only) and set `permissions.blockReadsOutsideWorkingDirectories: true` (safe, developer); deny paths use `//**/…` (filesystem-root anchor) because a plain `/x` in a `--settings` file anchors at the profile's own directory. (2) `developer.json` enables the native Bash sandbox (`autoAllowBashIfSandboxed: false`, `allowUnsandboxedCommands: false`); macOS/Linux/WSL2 only, native Windows runs unsandboxed. (3) Per current docs, path rules are consulted only for `Read`/`Edit` (a `Read` deny also blocks Write); explicit `Write(...)` denies are kept as requested but current CLI ignores them (may warn at startup). (4) Runner `--allowedTools` is derived from `permissions.allow` of the profile file (one source of truth); workspace override `.agentos/profiles/<p>.json` wins over the packaged file. (5) WIP for the queue = only the first `wip_limit` open A-tasks per project (priority, then ID) are pickable. (6) A task with no progress in 3 consecutive runs is set `blocked` (guard then creates the H-task). (7) Usage-limit output pauses the queue 60 min. (8) Guard extras: a task with the decision ID in `blocked_by` counts as its executor; created tasks carry back-refs `unblocks:` / `from_decision:`; optional decision key `executor:` (default `ceo`); blocked tasks whose blockers are all closed go back to `todo`; stale lock fields are cleared. (9) Run-now file entries: `{path, when (ISO), who}`, TTL 240 min, API `core.request_run_now` / `core.take_run_now`. (10) Notify state files: `.agentos/notify-buffer.jsonl`, `failures.jsonl`, `notified.json`, `digest.md` (kind=file).
- engine → installer: the scheduler launcher runs only `run` and `dashboard`; consider adding `guard` and `notify-digest` steps (each isolated).
- security review 2026-10-11 (docs/security-review-2026-10-11.md): runner adds `--permission-mode dontAsk` and `--tools` for safe/developer; profiles drop `Write(...)` rules (ignored by the CLI, warned on every run) and deny `Edit` on agentos.toml, agentos/**, .claude/settings*.json, .mcp.json, .git/**; developer also denies `git * --output*`/`--no-index*`/`--ext-diff*`/`--textconv*`; runner re-marks task files written during an external run as `source: external`; guard executor inherits an external decision's source; tick.py runs `python -P -m agentos`; a `claude_bin` resolving inside the workspace is refused; prompt role is whitelisted.
- integration 2026-10-11: demo has a second project `podcast-launch` (32 tasks total: 4 open decisions, one overdue; blocker chains two levels deep in both projects; no `lock:` values, so `guard` on a fresh copy is a no-op - tested in `tests/test_e2e_install.py`). Panel ideas follow `ideas/.templates/idea.md` (workspace copy, else the packaged one), file `ideas/<kebab-title>.md` with `-2`, `-3` on collision, then `ideas/index.md` is regenerated with the PACKAGED `add-idea/scripts/ideas_index.py` (the workspace copy is agent-writable, never imported). `python -m agentos panel` appends the repo root to `sys.path` before importing `panel`; the panel's run-now spawns `python -P -m agentos` like tick.py. The installer prints a "Next steps" block (workspace, repo folder, panel command, PYTHONPATH line). Closed tasks in panel lists show their closed date, not the old due date.
- integration 2026-10-11 (venv): `pyproject.toml` (setuptools, no runtime deps; packages agentos, agentos.scheduler, panel; data: `profiles/*.json` as `agentos/profiles`, `panel/static/*`, the idea template and `ideas_index.py` as `panel/_idea_template`, `panel/_add_idea`; console script `agentos`). install.py creates or reuses `<ws>/.agentos/venv` (stdlib venv) and runs `pip install --force-reinstall --no-deps` on a temp copy of the package (repo gets no build/ or egg-info); on failure retries `--no-build-isolation`, then writes `claude-agent-os-repo.pth` into the venv (offline fallback, reported, doctor warns). `--no-venv` skips it. New template placeholder `{{engine}}` replaces every `python -m agentos` in template/. Scheduler: the job interpreter is the venv pythonw/python, tick.py sets PYTHONPATH only without a venv. Doctor: new `engine` check. Uninstall also removes `.agentos/venv` (only if it has pyvenv.cfg). Profiles unchanged (venv is under the denied `.agentos/**`).
