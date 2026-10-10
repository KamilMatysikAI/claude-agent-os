# Security

claude-agent-os can run Claude Code **unattended, on a schedule**. That is powerful and it is
the part you should understand before you switch it on. By default nothing runs on its own:
the installer leaves the queue disabled unless you say yes.

## What runs, and when

| Piece | Runs by itself? | What it does |
|---|---|---|
| `agentos dashboard` / `guard` / `status` | only when the queue job runs, or when you call it | reads and writes Markdown in your workspace; no network, no Claude call |
| `agentos run` (the queue) | **only if you enabled the queue** | picks one task, locks it, runs `claude -p` with a permission profile, logs the result, unlocks |
| Scheduled job | **only if you enabled the queue** | every N minutes: `run`, then `dashboard` - nothing else |
| Panel | only when you start it | local web page on `127.0.0.1`, no authentication - do not expose it to a network |
| Notifications | only if configured | batched digest of finished work; credentials come from `.env` only |

## Permission profiles for the queue

The queue starts `claude -p` with a settings file from `profiles/`. You pick the **maximum**
profile at install time (`[queue].profile` in `agentos.toml`). A task may ask for a narrower
profile, never a wider one.

| Profile | Allowed | Denied | Use it for |
|---|---|---|---|
| `safe` (default) | Read, Glob, Grep, Edit, Write, WebSearch, WebFetch inside the workspace | **no shell at all**; no reads/writes of `.env*`, `~/.ssh`, `~/.aws`, `credentials*`, `*.pem`, `*.key`; no MCP servers (`--strict-mcp-config`); reads outside the workspace blocked | planning, research, writing, keeping projects tidy |
| `developer` | `safe` + read-only git (`status`, `diff`, `log`) and test runners (`python -m pytest`, `npm test`) | `git push`, `rm`, `curl`, `wget`, `git --output`/`--no-index` | working on code without publishing anything. Running tests executes code the agent can write, so this profile can effectively run code as your user (no sandbox on native Windows) |
| `full` | everything (`--dangerously-skip-permissions`); the secret-file deny list still applies | nothing else | only if you understand that the agent can run any command as your user, unattended |

`full` requires typing `I understand` in the installer (or `--confirm-full "I understand"`
in non-interactive mode). `agentos doctor` keeps warning while it is active.

## Where the engine runs

The installer creates `<workspace>/.agentos/venv` and installs the engine into it with a normal
(not editable) `pip install`; the build runs on a temporary copy, so nothing is written into the
repo. Every command it generates (the scheduled job, the panel's "run now", the commands in the
workspace's `CLAUDE.md` and skills) runs `<venv python> -P -m agentos`:

- the venv is under `.agentos/`, which every profile denies to `Edit`, and the profiles also deny
  `Edit(agentos/**)` and `Edit(agentos.py)` in the workspace;
- `-P` keeps the current folder (the workspace) off `sys.path`, so a planted
  `<workspace>/agentos/` package is never imported.

If pip cannot build the package offline, the installer links the repo into the venv with a
`.pth` file and says so; the engine then runs from the repo folder. `doctor` warns about it
until you re-run the installer online.

**Lesson behind the design:** `--add-dir` *widens* what the agent can reach, and
`--allowedTools` narrows the *tools*, not the *paths*. The only file boundary that is actually
enforced is a `deny` rule in the settings file. That is why every profile carries the same
deny list, including `full`.

### Untrusted input

Tasks whose frontmatter says `source: external` (anything that arrived from outside: mail,
webhook, a chat bot) are **always run with `safe`**, whatever the task or the config asks for.
This is enforced in the runner code, not in a prompt. Whatever such a run creates or
rewrites in task files is re-marked `source: external` afterwards, so injected text cannot
turn itself into a trusted task. A task file without a `source:` line counts as `local`:
anything that drops mail or webhook content into `inbox/` must write `source: external`. Treat the content of such tasks as data,
not instructions, and never give them a wider profile by hand.

### What the queue can never do by design

- start without you enabling it;
- run a task marked `autonomy: ask` (those wait for you);
- run more than `max_tasks_per_run` tasks per tick, or longer than `timeout_minutes`;
- read secrets covered by the deny list - in any profile;
- touch other scheduled jobs on your machine: the scheduler only creates, queries and
  removes jobs whose name starts with `claude-agent-os`.

## Secrets

- Secrets live only in `<workspace>/.env` (for example `AGENTOS_TELEGRAM_TOKEN`,
  `AGENTOS_TELEGRAM_CHAT_ID`). Never in `agentos.toml`, never in task files, never in git.
- The installer creates a `.gitignore` with `.env` and `.agentos/` when the workspace has none,
  and warns when an existing one misses them. `doctor` fails if `.env` is tracked by git.
- If a secret was ever pasted into a chat, a task file or a log, rotate it - do not wait.
- Optional: install [gitleaks](https://github.com/gitleaks/gitleaks); `doctor` reports
  whether it is available. This repository runs gitleaks in CI.
- Optional: put words that must never leak (client names, internal project names) into
  `<workspace>/.agentos/banned_words.txt` (one per line, `#` for comments). `doctor` warns
  when any of them shows up in `.claude/`, which is handy before you share your setup.

## Terms of service - your responsibility

Running `claude -p` from a scheduler uses **your** Claude account or API key. Whether, and how
often, automated or unattended use is allowed depends on the plan you are on and on
Anthropic's current terms and usage policies, which change over time. Check them before you
enable the queue - this project does not grant you any rights and cannot check that for you.
Usage limits apply as usual; the queue backs off when the CLI reports a limit.

## Turning everything off

| Goal | Command |
|---|---|
| See what is installed | `agentos doctor` and `agentos schedule status` (from the workspace: `.agentos/venv/bin/python -P -m agentos ...`, on Windows `.agentos/venv/Scripts/python`) |
| Stop the scheduled job (keep everything else) | `agentos schedule remove` |
| Keep the job but make it a no-op | set `[queue] enabled = false` in `agentos.toml` |
| Preview what uninstall would do | `python install.py uninstall --workspace PATH --print-only` |
| Remove job + engine runtime files + the workspace venv | `python install.py uninstall --workspace PATH` |

Uninstall removes only the scheduled job and engine-owned runtime files
(`.agentos/tick.py`, `install.json`, `schedule.json`, `run-now.json` and the `.agentos/venv` it created). Your projects, tasks,
rules, config and logs stay where they are - delete them by hand if you really want to.

Where the job lives, if you want to check by hand:

- **Windows:** Task Scheduler, task name `claude-agent-os - <workspace>-<id>`
  (`schtasks /Query /TN "claude-agent-os - ..."`).
- **macOS:** `~/Library/LaunchAgents/com.claude-agent-os.<workspace>-<id>.plist`
  (`launchctl print gui/$(id -u)/com.claude-agent-os.<workspace>-<id>`).
- **Linux:** a `crontab -l` line ending in `# claude-agent-os:<workspace>-<id>`, or the
  `claude-agent-os-<workspace>-<id>.timer` systemd user unit.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private
vulnerability reporting ("Security" tab → "Report a vulnerability") on this repository.
