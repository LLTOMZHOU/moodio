#!/usr/bin/env python3
"""Fast-forward the current checkout to origin/<branch> on session start when safe."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckoutTarget:
    branch: str
    label: str


def run(command: list[str], *, cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def git(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=cwd)


def emit_message(*, system: str | None = None, context: str | None = None) -> None:
    payload: dict[str, object] = {}
    if system:
        payload["systemMessage"] = system
    if context:
        payload["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    if payload:
        print(json.dumps(payload))


def is_git_repo(cwd: str) -> bool:
    result = git(cwd, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def resolve_checkout_target(cwd: str) -> CheckoutTarget | None:
    current_branch = git(cwd, "symbolic-ref", "--short", "-q", "HEAD")
    if current_branch.returncode == 0:
        branch = current_branch.stdout.strip()
        if branch:
            return CheckoutTarget(branch=branch, label=f"branch `{branch}`")

    remote_refs = git(
        cwd,
        "for-each-ref",
        "--format=%(refname:short)",
        "--points-at",
        "HEAD",
        "refs/remotes/origin",
    )
    if remote_refs.returncode != 0:
        return None

    candidates = [
        line.removeprefix("origin/")
        for line in remote_refs.stdout.splitlines()
        if line and line != "origin/HEAD" and line.startswith("origin/")
    ]
    if len(candidates) != 1:
        return None

    branch = candidates[0]
    return CheckoutTarget(
        branch=branch,
        label=f"detached HEAD mapped to `origin/{branch}`",
    )


def has_local_changes(cwd: str) -> bool:
    status = git(cwd, "status", "--short")
    return status.returncode == 0 and bool(status.stdout.strip())


def ref_exists(cwd: str, ref: str) -> bool:
    result = git(cwd, "rev-parse", "--verify", "--quiet", ref)
    return result.returncode == 0


def is_ancestor(cwd: str, older_ref: str, newer_ref: str) -> bool:
    result = git(cwd, "merge-base", "--is-ancestor", older_ref, newer_ref)
    return result.returncode == 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return 0

    if not is_git_repo(cwd):
        return 0

    target = resolve_checkout_target(cwd)
    if target is None:
        emit_message(
            system="Startup sync skipped: could not determine a unique branch for this checkout.",
            context=(
                "This session started on a checkout without a unique branch mapping to origin. "
                "If the user asks to sync, inspect the git state first and confirm which branch "
                "should be updated."
            ),
        )
        return 0

    fetch = git(cwd, "fetch", "origin", "--prune")
    if fetch.returncode != 0:
        message = fetch.stderr.strip() or fetch.stdout.strip() or "unknown git fetch error"
        emit_message(
            system=(
                f"Startup sync skipped for {target.label}: `git fetch origin --prune` failed: {message}"
            )
        )
        return 0

    remote_ref = f"origin/{target.branch}"
    if not ref_exists(cwd, remote_ref):
        emit_message(
            system=(
                f"Startup sync skipped for {target.label}: remote ref `{remote_ref}` does not exist."
            )
        )
        return 0

    local_changes = has_local_changes(cwd)

    if not is_ancestor(cwd, "HEAD", remote_ref):
        if is_ancestor(cwd, remote_ref, "HEAD"):
            return 0

        emit_message(
            system=(
                f"Startup sync skipped for {target.label}: local history diverges from `{remote_ref}`."
            ),
            context=(
                f"The current checkout diverges from `{remote_ref}`. Ask the user before attempting "
                "to reconcile or rebase this branch."
            ),
        )
        return 0

    head_rev = git(cwd, "rev-parse", "HEAD")
    remote_rev = git(cwd, "rev-parse", remote_ref)
    if head_rev.returncode != 0 or remote_rev.returncode != 0:
        return 0

    if head_rev.stdout.strip() == remote_rev.stdout.strip():
        return 0

    if local_changes:
        emit_message(
            system=(
                f"Startup sync skipped for {target.label}: checkout is behind `{remote_ref}` and has local changes."
            ),
            context=(
                f"Before editing, ask the user whether to sync `{target.branch}` with `{remote_ref}`. "
                "If they approve, inspect, stash, or commit the local changes first and then fast-forward."
            ),
        )
        return 0

    merge = git(cwd, "merge", "--ff-only", remote_ref)
    if merge.returncode != 0:
        message = merge.stderr.strip() or merge.stdout.strip() or "unknown git merge error"
        emit_message(
            system=(
                f"Startup sync failed for {target.label}: could not fast-forward to `{remote_ref}`: {message}"
            )
        )
        return 0

    emit_message(
        system=f"Startup sync fast-forwarded {target.label} to `{remote_ref}`."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
