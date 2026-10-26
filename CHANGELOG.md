# Changelog

Every release is listed here, newest first. Each entry says what changed and whether you
have to do anything after updating.

How to update: `git pull`, then run `python install.py` again with the same workspace.
The installer reinstalls the engine and leaves your files alone.

## 0.1.2 - 2026-10-26

- New command `usage`: token usage per session and per subagent from the Claude Code logs on
  your machine (`python -P -m agentos usage`, `--hours 168` for a week). It flags background
  agents that keep rewriting their whole prompt cache or grow a huge context. Nothing is sent anywhere.
- New rule 41 in `04-multi-agent.md`: a background agent never waits longer than about 4 minutes in
  one call and hands over to a fresh agent after 2 to 3 hours. Behind it: five coding agents used
  about 70% of a weekly limit in under a day by sleeping 10 minutes at a time with a 5-minute cache.

After updating: run `python install.py` again. The `usage` command works right away. The installer
never overwrites your rule files, so it leaves the new version as `.claude/rules/04-multi-agent.md.new`;
Claude Code does not read `.new` files. Copy rule 41 from it into `04-multi-agent.md` (or replace the
file with the `.new` one if you never edited it), then delete the `.new` file.

## 0.1.1 - 2026-10-13

- Panel: starts right away on machines where a reverse DNS lookup is slow (seen on macOS,
  where the first page could take over 20 seconds to appear).
- CI: secret scan runs with the gitleaks CLI; the start-up test says why the panel did not answer.

After updating: nothing to do.

## 0.1.0 - 2026-10-13

First public release.

- Engine: projects, tasks and decisions in plain Markdown files, the agent queue with the
  `safe`, `developer` and `full` profiles, the guard, the dashboard, digests.
- Local web panel in English and Polish: Today, Decisions, Projects, Activity, All tasks, Tree.
- Installer with a setup wizard, scheduler integration for Windows, macOS and Linux, `doctor`.
- Workspace template: six roles, the rules, eleven skills, a demo workspace in both languages.
- The panel tells you when a newer release is out. It asks the public GitHub API once a day,
  sends nothing about your workspace, and installs nothing. Turn it off with
  `[updates] check = false` in `agentos.toml` or `AGENTOS_NO_UPDATE_CHECK=1`.
- Sidebar link to the author's e-mail list for release announcements.

After updating: nothing to do.
