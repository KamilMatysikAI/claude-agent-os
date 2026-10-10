# Security and correctness review - 2026-10-11

Scope: `agentos/` (core, runner, guard, notify, config, scheduler, doctor), `install.py`,
`profiles/*.json`. Live probes were run against Claude Code 2.1.296 on native Windows in a
throwaway workspace with dummy secrets (`.env`, `credentials.json`) and a dummy file one
directory above the workspace. `panel/` was out of scope (only noted).

Test suite after the fixes: `pytest tests -q` -> 151 passed.

## Live profile probe

Each action was attempted once by a `claude -p` session started with the exact argv the
runner builds (prompt swapped for the probe). "Before" = command and profiles as they were
at the start of the review; "after" = with the fixes below.

| # | Action | safe before | safe after | developer after |
|---|---|---|---|---|
| 1 | Read `.env` | denied | denied | denied |
| 2 | Read `credentials.json` | denied | denied | denied |
| 3 | Read file outside the workspace | denied | denied | denied |
| 4 | Read `notes.txt` (control) | allowed | allowed | allowed |
| 5 | Write `.agentos/tick.py` | denied | denied | denied |
| 6 | Write `agentos.toml` (`profile = "full"`) | **ALLOWED** | denied | denied |
| 7 | Write `.claude/settings.local.json` | **ALLOWED** | denied | denied |
| 8 | Write `agentos/__init__.py` (shadow package) | **ALLOWED** | denied | denied |
| 9 | Write `.git/probe.txt` | **ALLOWED** | denied | denied |
| 10 | Shell `echo hi` | **ALLOWED** | no shell tool at all | allowed (read-only) |
| 10b | Shell `mkdir`, `python -c` | **ALLOWED** (auto mode) / denied with dontAsk | no shell tool | denied |
| 11 | `git status --short`, `git log --oneline` | - | - | allowed |
| 12 | `curl` | - | - | denied |
| 13 | `rm dummy.txt` | - | - | denied |
| 14 | `git status && cat .env` | - | - | denied |
| 15 | `git log --output=FILE` (arbitrary file write) | - | - | **allowed before fix**, denied after |
| 15b | `git diff --no-index .env notes.txt` | - | - | denied |
| 16 | write `test_probe.py` + `python -m pytest` | - | - | **allowed** (by design: code execution) |

Why 10 was allowed in `safe`: the session inherited `defaultMode: auto` from the user's own
`~/.claude/settings.json`, so the auto-mode classifier approved shell commands that were not
in `--allowedTools`. With `--permission-mode dontAsk` non-read-only commands were denied but
`echo` still ran (built-in read-only auto-approval); `--tools` removes the shell entirely.
The session also had Agent, Workflow, CronCreate, RemoteTrigger, PowerShell and
PushNotification available before `--tools` was added.

## Findings

| # | Severity | Where | Finding | Status |
|---|---|---|---|---|
| 1 | Critical | `profiles/*.json` | A `safe` run could rewrite `agentos.toml` (`profile = "full"`, `claude_bin`), so the next run escalated itself to `--dangerously-skip-permissions` or ran a planted binary. Live-confirmed (probe 6). | Fixed: `Edit(agentos.toml)` denied in every profile. |
| 2 | Critical | `profiles/*.json` | `.claude/settings.local.json` / `.claude/settings.json` were writable: hooks run shell commands in the next session regardless of tool permissions; allow rules widen it. Live-confirmed (probe 7). | Fixed: `Edit(//**/.claude/settings.json)`, `Edit(//**/.claude/settings.local.json)`, `Edit(.mcp.json)`. |
| 3 | Critical | `agentos/scheduler/__init__.py:230` (launcher) | `tick.py` ran `python -m agentos` with cwd = workspace, so `<workspace>/agentos/__init__.py` written by a `safe` session would be imported and executed unsandboxed on the next tick (also when the user runs `python -m agentos` in the workspace). Live-confirmed write (probe 8). | Fixed: launcher uses `python -P -m agentos`; profiles deny `Edit(agentos/**)` and `Edit(agentos.py)`. Test added. |
| 4 | Critical | `agentos/runner.py` `build_command` | The session inherited the user's `defaultMode` (auto here) and the full built-in tool set; `safe` was not shell-free. Live-confirmed (probe 10). | Fixed: `--permission-mode dontAsk` and `--tools <allow base names>` for safe/developer. Tests added. |
| 5 | High | `agentos/runner.py` `execute` | Injection laundering: a run of a `source: external` task could write a new task (or edit an existing one, or flip its own `source:`) to `source: local` + `profile: full`; the next run executed it at the config maximum. | Fixed: after an external run every task file it created or changed is re-marked `source: external`, its own source is restored. Test added. |
| 6 | High | `agentos/guard.py:84` | An accepted decision written during an external run produced an executor with `source: local` quoting the untrusted `## For approval` text. | Fixed: executor inherits `external`. Test added. |
| 7 | High | `profiles/developer.json` | `Bash(git log:*)` / `Bash(git diff:*)` allowed `--output=FILE` (arbitrary file write that bypasses the Edit deny list, e.g. onto `agentos.toml`). Live-confirmed (probe 15). `--no-index` can diff arbitrary files. | Fixed: deny `Bash(git * --output*)`, `--no-index*`, `--ext-diff*`, `--textconv*`. Live re-probe denied. |
| 8 | High | `profiles/*.json` | `.git/**` writable: `core.fsmonitor` in `.git/config` runs on `git status` (developer). Live-confirmed write (probe 9). | Fixed: `Edit(//**/.git/**)`. |
| 9 | Important (design, documented) | `profiles/developer.json` | `python -m pytest` / `npm test` execute code the agent writes (`conftest.py`, test files, `package.json` scripts): developer = code execution as the user; the `rm`/`curl` denies do not hold against it. On native Windows the Bash sandbox is off (CLI prints "Sandbox disabled ... restrictions will NOT be enforced"). | Documented in SECURITY.md and profiles/README.md. Not fixable by settings. Consider `sandbox.failIfUnavailable: true` as the default on macOS/Linux. |
| 10 | Important | `profiles/*.json` | `Write(...)` deny rules are ignored by the current CLI and printed 7 warnings into every run log. | Fixed: removed (Read/Edit rules enforce; live-confirmed). Test updated. |
| 11 | Important | `agentos/runner.py:105` `build_prompt` | `owner` from the task file went verbatim into the argv. If `claude` resolves to a `.cmd` shim (npm install on Windows) the argv passes through cmd.exe, where a crafted owner with quotes could break quoting. | Fixed: role whitelisted against `core.ROLES`, else `soft`. Test added. |
| 12 | Important | `agentos/runner.py` `resolve_bin` | A `claude_bin` that resolves inside the workspace (agent-writable) was accepted. On this machine `shutil.which` did not search cwd, but behaviour depends on Python/Windows settings. | Fixed: refused with `UnsafeBinary`. Test added. |
| 13 | Important | `agentos/runner.py:35` `SECRET_ENV_RE` | `AWS_ACCESS_KEY_ID`, `*_KEY`, `*_DSN`, `DATABASE_URL`, webhook URLs passed into developer sessions (reachable via test code). | Fixed: pattern widened. Test added. |
| 14 | Important | `agentos/runner.py` `resolve_profile` | A task without `source:` counts as `local`, and any file can claim `source: panel`. Trust rests on whoever writes into `inbox/`. | Not changed (contract default). Documented in SECURITY.md: ingesters must write `source: external`. Option: treat missing `source` in `inbox/` as external. |
| 15 | Minor | `agentos/core.py:58` `LOCK_ALIVE_MIN` vs `queue.timeout_minutes` | With `timeout_minutes` > ~75 the guard (run every tick) clears the lock of a still-running task after 90 min; a panel/interactive session could then take it. The workspace-level runner lock still prevents a second queue run. | Not fixed. Suggest clamping `timeout_minutes` <= 75 in `config.normalize` or making the alive window `max(90, timeout + 15)`. |
| 16 | Minor | `agentos/runner.py` `profile_path` | A workspace override `.agentos/profiles/safe.json` also applies to forced-safe external tasks. Protected from the agent (`.agentos/**` denied), but a user may relax it unknowingly. | Not fixed. Suggest `doctor` warns when overrides exist and diff them against the packaged profile. |
| 17 | Minor | `agentos/core.py:263` `write_text_atomic` | Temp name uses only the pid; two threads of one process (panel) writing the same file can collide. | Not fixed. Suggest `pid + thread id` or `tempfile.mkstemp` in the same directory. |
| 18 | Info | `--tools`, `dontAsk`, `blockReadsOutsideWorkingDirectories` | Need a recent CLI (verified on 2.1.296). Older CLIs may reject `--tools`. | Suggest `doctor` checks `claude --version` against a minimum. |
| 19 | Info | `notify.py` | Telegram token only from env/.env, scrubbed from error text, not passed to child sessions (`AGENTOS_TELEGRAM*` dropped in every profile). OK. | - |
| 20 | Info | scheduler | All three backends assert the product prefix before create/query/delete; crontab rewrite keeps foreign lines; Windows uses `/TN <own name> /F` only. OK. | - |
| 21 | Info | `install.py` | Never overwrites a differing file (`.new` next to it), `full` needs the typed confirmation, uninstall removes only four engine-owned files. OK. | - |
| 22 | Info | `panel/server.py` | Host allowlist and Origin check on POST are present. Panel-created tasks are `source: panel` (trusted, run at config maximum): any local process that can reach the port can queue work. Keep the "do not expose" warning. | Reported only. |

## Private-data scan

- `tests/test_clean_repo.py`: 3 passed.
- Private plain list (kept outside the repo): 2 hits, both `LICENSE:3` (the author's name in the
  copyright line, `K***l M*****k`). The clean-repo test allowlists exactly that line on purpose;
  confirm the real name is wanted in the public LICENSE (alternative: "claude-agent-os contributors").
- Regex scan for drive paths, home paths and e-mail addresses: no hits.
- gitleaks v8.21.2 (`detect --no-git --redact`, run in a read-only Docker container): no leaks found.

## Not done / follow-ups

- `full` profile was not probed live (by instruction).
- macOS/Linux sandbox behaviour of `developer` not measured (native Windows only).
- A `doctor` check for a minimum CLI version and for workspace profile overrides (findings 16, 18).
