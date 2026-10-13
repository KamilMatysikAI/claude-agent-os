# Changelog

Every release is listed here, newest first. Each entry says what changed and whether you
have to do anything after updating.

How to update: `git pull`, then run `python install.py` again with the same workspace.
The installer reinstalls the engine and leaves your files alone.

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
