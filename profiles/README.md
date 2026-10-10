# Permission profiles for queue runs

The runner passes one of these files to `claude -p` with `--settings`, together with
`--strict-mcp-config` (no MCP servers) and cwd = your workspace. The tool list for
`--allowedTools` is taken from `permissions.allow` of the same file, so there is one source
of truth per profile. For `safe` and `developer` the runner also passes
`--permission-mode dontAsk` (anything not pre-approved is denied, whatever `defaultMode`
your own user settings use) and `--tools <base names of the allow list>` (the session does
not even get Agent, Cron, PowerShell or Bash unless the profile allows it).

| Profile | Command flags | Use for |
|---|---|---|
| `safe` (default) | `--allowedTools` from the file, no Bash, no `--dangerously-skip-permissions` | planning, research, writing, tidying projects |
| `developer` | `safe` + read-only git, `python -m pytest`, `npm test`; push, `rm`, `curl`, `wget`, `git --output/--no-index` denied | code work without publishing. NOTE: running tests runs code the agent can write (a test file, `conftest.py`, `package.json` scripts) - treat `developer` as "can execute code as your user"; on native Windows there is no sandbox |
| `full` | `--dangerously-skip-permissions` + the same deny list | only if you understand the risk; never for external sources |

Tasks with `source: external` always run in `safe`, whatever the config or the task says.
This is enforced in the runner code, not in the prompt.

## What actually enforces a boundary (measured, not assumed)

- `--add-dir` WIDENS access. It is a scope declaration, not a cage.
- `--allowedTools` narrows the SET OF TOOLS, not the paths those tools may touch.
- The file boundary that holds is the `deny` list in the `--settings` file. It is a
  blocklist of sensitive targets, not an allowlist of directories: a path that is not on
  the list stays writable.
- Current Claude Code checks path rules only for `Read(...)` and `Edit(...)`. A `Read`
  deny also blocks `Edit` and `Write` on the same path (recent versions); the explicit
  `Edit` rules cover older versions and notebook edits. `Write(path)` rules are not used:
  current versions ignore them and print a warning on every run (measured 2026-10-11).
- `//**/x` is anchored at the filesystem root (any drive on Windows), `~/x` at the home
  directory. A plain `/x` would be anchored at the directory of the settings file, which is
  why it is not used.
- Deny rules apply to Claude's file tools and to file commands Claude Code recognises in
  Bash (`cat`, `head`, redirections). They do NOT stop a script that opens files itself
  (`python -c "open(...)"`). That is why `safe` has no Bash at all.
- `permissions.blockReadsOutsideWorkingDirectories` (Claude Code 2.1.257+) makes the file
  tools refuse reads outside the workspace. Older versions ignore the key.
- Files that steer the NEXT run are denied for `Edit` in every profile: `.agentos/**`
  (locks, run-now requests, the scheduled `tick.py`, workspace profile overrides),
  `agentos.toml` (profile maximum, `claude_bin`), `.claude/settings.json` and
  `.claude/settings.local.json` (hooks and allow rules would run or widen the next session),
  `.mcp.json`, `.git/**` (`core.fsmonitor` runs on `git status`) and `agentos/` /
  `agentos.py` in the workspace (a shadow package for `python -m agentos`). Without these a
  `safe` run could raise its own next run to `full` (measured live before the fix).
- Everything a run of an external task creates or rewrites under `projects/*/tasks` and
  `inbox/` is re-marked `source: external` by the runner afterwards, and an accepted decision
  that is external yields an external executor task, so injected text cannot launder
  itself into a `local` task.

## Bash sandbox in `developer`

Claude Code has a native OS-level sandbox for Bash (macOS, Linux and WSL2; on native Windows
commands run unsandboxed). `developer.json` turns it on with:

- `autoAllowBashIfSandboxed: false` - the sandbox is an extra layer, it does not widen the
  allowlist (with the default `true`, any sandboxed command would run without approval);
- `allowUnsandboxedCommands: false` - a command that fails inside the sandbox is not retried
  outside it.

If the sandbox cannot start (missing `bubblewrap`/`socat` on Linux, native Windows), Claude
Code runs the allowed commands without it. Set `"failIfUnavailable": true` under `sandbox`
if you want the run to stop instead.
