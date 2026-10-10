# 04 · Many agents at once

Several sessions often work at the same time: the scheduled queue, a terminal session, subagents. These rules keep them from destroying each other's work.

---

## 23. One worktree per agent, removed after merge

**Rule.** An agent changing code works in its own `git worktree`. After merging to main it runs `git worktree remove <path>` (without `--force`) and deletes the merged branch. Before starting a wave of agents, check free disk (about 2 GB per agent) and free memory. Do not limit the number of agents; limit the garbage.

**Why.** Seventy-two leftover worktrees, about 1 GB each with dependencies and build cache, filled the system disk to zero bytes. A write that failed in that state emptied three task files. Another repository had over a hundred leftover copies the next day.

**How to apply.** The last line of a coding report says "worktree removed: yes" or "no, because...". Bulk cleanup of others' copies only when they are merged, have no uncommitted changes, and had no git activity in the last 3 hours.

## 24. Read the fresh project log before changing shared state

**Rule.** Before any change to shared production state (database, tenant config, deployment), read the project's latest `LOG.md` or progress file. A warning written by another session applies to yours.

**Why.** A night session discovered that a setup command wiped a production configuration and wrote "DO NOT RUN" in the progress file. An evening session did not read it and repeated the incident on a second production system.

**How to apply.** Make "read the last 20 lines of the log" a step before every mutating command. When you learn something dangerous, write it in the log at once, in capitals, with the command name.

## 25. Commit by file name in a shared repository

**Rule.** In a repository where other sessions may have uncommitted work, stage your files by name. Never `git add -A` or `git add .`. Before pushing, run `git show --stat HEAD` and confirm every file is yours.

**Why.** A broad `git add` swept another session's unfinished change into a commit. It imported a file that existed only on disk, so the local build passed and the server build would have failed. Git's warning about a file the agent never touched was the only signal.

**How to apply.** A local build is not proof the clean repository builds. If you committed someone else's file by mistake, revert that file in the repository and restore its content in the working tree. Never delete the other session's work.

## 26. Lock only after a fresh read

**Rule.** Take a task's lock only after reading its frontmatter and its last log line in the same minute, and after checking whether a queue run is active. A candidate list from earlier is a hint, not a basis for a lock.

**Why.** A terminal session locked a task based on a list from an hour earlier. The scheduled queue had taken the same task five minutes before and its subagent was already writing data. Only the second session noticing the other's log entry prevented a lost update on three files.

**How to apply.** If the task log has an entry from another session in the last 90 minutes, stop and report. Put that clause into subagent prompts.

## 27. Stop only what you started

**Rule.** Agents and scripts never kill processes by name (`pkill python`, `taskkill /IM`, `Stop-Process -Name`) and never stop a shared daemon (browser automation server, containers, services). Remember the PID of what you launched and stop only that.

**Why.** After local tests an agent killed every Python process on the machine. The chat bot, the queue runners and other agents' tools all run on Python; they survived by luck. Another time an agent stopped a shared browser daemon and six other sessions lost their logins.

**How to apply.** Close your own browser profile or tab, never the daemon. Search agent logs for `taskkill`, `pkill` and `Stop-Process -Name` as a warning sign.

## 28. Subagents get the rules in their prompt

**Rule.** When you hand work to a subagent, its prompt includes: the STOP-on-refusal rule, the "stop only what you started" rule, the task file path, and where to write evidence.

**Why.** Rules in your context are not in the subagent's context. Several of the incidents above were caused by subagents that never saw the rule their parent session followed.

**How to apply.** Keep a short standard block for subagent prompts and paste it every time. It costs a few lines and has prevented repeat incidents.
