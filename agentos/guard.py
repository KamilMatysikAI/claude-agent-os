"""Guard: turns silent waiting into explicit tasks. Idempotent, never deletes anything.

Rules (CONTRACT):
1. `status: blocked` without a valid `unblocked_by` -> create a human mini-task (H-*) and
   point `unblocked_by` at it. "Waiting for the owner" without a task is not allowed:
   commitments that live only in someone's head stall work for weeks.
2. Accepted decision without an executing A-task -> create one (due = accept + 2 days,
   quoting `## For approval`). Clicking "accept" does not execute anything by itself.
3. Blocked task whose blockers are all closed (`blocked_by` items and the `unblocked_by`
   task) -> back to `todo`.
4. Task locks older than the alive window are cleared (a killed run must not hold a task).
5. WIP over limit and done-without-evidence are reported (dashboard shows them too).

Idempotency: created tasks carry a back-reference (`unblocks:` / `from_decision:`). Before
creating anything the guard looks for an existing task with that reference, so a crash
between "create" and "update the original" never produces a duplicate on the next run.
Each element is processed in its own try/except: one broken file never stops the rest.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from . import core


def _ref_exists(snap: core.Snapshot, project: str, key: str, task_id: str) -> core.Task | None:
    for task in snap.tasks:
        if task.project == project and str(task.get(key)).strip() == task_id:
            return task
    return None


def _unblock_task(ws, snap, task, cfg, today, actions, dry_run):
    ref = task.id or task.path.name
    existing = _ref_exists(snap, task.project, "unblocks", ref)
    if existing is None:
        action = task.section("Unblocking action") or (
            "The agent did not describe what it needs. Open the task, read the latest "
            "progress log line and decide what unblocks it.")
        max_min = cfg["projects"]["human_task_max_minutes"]
        title = f"Unblock {ref}: {task.title}"[:120]
        actions.append(f"create human task: {title}")
        if dry_run:
            return
        existing = core.create_task(
            ws, title=title, owner="human", project=task.project, type="task",
            priority=task.s("priority") or "normal",
            due=(today + timedelta(days=1)).isoformat(), size="small",
            autonomy="ask", source="local", today=today, unblocks=ref,
            sections={
                "Goal": f"Unblock agent task {ref} ({task.title}). Keep it under "
                        f"{max_min} minutes; first step: open `{task.path.name}`.",
                "Unblocking action": action,
                "Definition of done": f"{ref} can continue; close this task with evidence.",
                "Progress log": "",
            })
        snap.tasks.append(existing)
    if existing.id and str(task.get("unblocked_by")).strip() != existing.id:
        actions.append(f"{ref}: unblocked_by -> {existing.id}")
        if not dry_run:
            fresh = core.read_task(task.path)
            fresh.meta["unblocked_by"] = existing.id
            core.append_progress(fresh, f"guard: waiting for human task {existing.id}",
                                 write=False)
            core.write_task_atomic(fresh)


def _executor_for(snap, decision, cfg, today, ws, actions, dry_run):
    ref = decision.id or decision.path.name
    if _ref_exists(snap, decision.project, "from_decision", ref):
        return
    # a task that waits for this decision (blocked_by) is its executor as well
    if any(t.project == decision.project and ref in t.list("blocked_by") for t in snap.tasks):
        return
    accepted_on = core.parse_date(decision.get("closed")) or today
    owner = decision.s("executor") or "ceo"
    if owner not in core.ROLES or owner == "human":
        owner = "ceo"
    approval = decision.section("For approval") or "(the decision has no `## For approval` section)"
    # An untrusted decision (written by a run of an external task) yields an untrusted
    # executor: accepting it must not upgrade its quoted text to the config maximum profile.
    source = "local" if (decision.s("source") or "local") in ("local", "panel") else "external"
    title = f"Execute decision {ref}: {decision.title}"[:120]
    actions.append(f"create executor task: {title}")
    if dry_run:
        return
    created = core.create_task(
        ws, title=title, owner=owner, project=decision.project, type="task",
        priority=decision.s("priority") or "normal",
        due=(accepted_on + timedelta(days=2)).isoformat(), size="medium",
        autonomy="full", source=source, today=today, from_decision=ref,
        sections={
            "Goal": f"Carry out the accepted decision {ref}.",
            "Context": "Accepted version (quoted from the decision):\n\n"
                       + "\n".join(f"> {ln}" if ln else ">" for ln in approval.splitlines()),
            "Definition of done": "What the decision describes is done; evidence attached.",
            "Progress log": "",
        })
    snap.tasks.append(created)


def _blockers_closed(snap, task) -> bool:
    refs = task.list("blocked_by")
    unblocker = str(task.get("unblocked_by")).strip()
    if unblocker:
        refs.append(unblocker)
    if not refs:
        return False
    for ref in refs:
        other = snap.by_id(task.project, ref)
        if other is None or other.status not in core.CLOSED_STATUSES:
            return False
        if other.s("type") == "decision" and other.s("decision") == "rejected":
            return False  # a rejected decision does not unblock; the owner must re-plan
    return True


def run_guard(workspace, cfg: dict | None = None, now: datetime | None = None,
              dry_run: bool = False) -> dict:
    ws = Path(workspace)
    cfg = cfg or core.load_config(ws)
    moment = now or core.now_local(cfg)
    today = moment.date()
    snap = core.load_snapshot(ws)
    actions: list[str] = []
    errors: list[str] = list(snap.errors)
    known = {t.project for t in snap.tasks} | set(snap.projects)
    tasks = list(snap.tasks)

    for task in tasks:
        try:
            if task.status == "blocked":
                unblocker = str(task.get("unblocked_by")).strip()
                if not unblocker or snap.by_id(task.project, unblocker) is None:
                    _unblock_task(ws, snap, task, cfg, today, actions, dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad element never stops the guard
            errors.append(f"{task.path}: blocked rule: {exc}")

    for task in tasks:
        try:
            if (task.s("type") == "decision" and task.s("decision") == "accepted"
                    and task.project in known):
                _executor_for(snap, task, cfg, today, ws, actions, dry_run)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{task.path}: decision rule: {exc}")

    for task in tasks:
        try:
            if task.status == "blocked" and _blockers_closed(snap, task):
                actions.append(f"{task.id or task.path.name}: blockers closed -> todo")
                if not dry_run:
                    core.set_status(core.read_task(task.path), "todo",
                                    note="guard: all blockers closed", now=moment)
            lock = str(task.get("lock")).strip()
            if lock and not core.lock_alive(lock, moment):
                actions.append(f"{task.id or task.path.name}: stale lock cleared")
                if not dry_run:
                    core.release_lock(task.path, token=lock)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{task.path}: unblock/lock rule: {exc}")

    wip = core.wip_counts(snap.tasks)
    warnings = []
    for slug, count in sorted(wip.items()):
        limit = snap.wip_limit(slug, cfg["projects"]["wip_limit"])
        if count > limit:
            warnings.append(f"{slug}: WIP {count} over limit {limit}")
    for task in snap.tasks:
        if task.status == "done" and not str(task.get("evidence")).strip():
            warnings.append(f"{task.id or task.path.name}: done without evidence")

    for line in actions:
        core.log(ws, "guard", ("[dry-run] " if dry_run else "") + line)
    for line in errors:
        core.log(ws, "guard", f"ERROR {line}")
    return {"actions": actions, "warnings": warnings, "errors": errors}
