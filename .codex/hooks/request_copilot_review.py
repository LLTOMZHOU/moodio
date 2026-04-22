#!/usr/bin/env python3
"""Request GitHub Copilot review after Codex creates a PR with gh."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any


PR_CREATE_RE = re.compile(r"(?<!\S)gh\s+pr\s+create\b")


def run_json(command: list[str]) -> Any:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def get_requested_reviewers(pr_number: int) -> set[str]:
    payload = run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "reviewRequests",
        ]
    )
    reviewers: set[str] = set()
    for request in payload.get("reviewRequests", []):
        if isinstance(request, dict):
            reviewer = request.get("requestedReviewer")
            if isinstance(reviewer, dict):
                login = reviewer.get("login")
                if isinstance(login, str):
                    reviewers.add(login.lower())
                    continue
            login = request.get("login")
            if isinstance(login, str):
                reviewers.add(login.lower())
    return reviewers


def system_message(message: str) -> None:
    print(json.dumps({"systemMessage": message}))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not PR_CREATE_RE.search(command):
        return 0

    pr_view = run(
        [
            "gh",
            "pr",
            "view",
            "--json",
            "number,url,reviewRequests",
        ]
    )
    if pr_view.returncode != 0:
        system_message(
            "Detected `gh pr create`, but could not find the current branch PR to request Copilot review."
        )
        return 0

    pr_payload = json.loads(pr_view.stdout)
    pr_number = pr_payload["number"]
    pr_url = pr_payload["url"]

    existing_reviewers = get_requested_reviewers(pr_number)
    if "copilot" in existing_reviewers or "@copilot" in existing_reviewers:
        return 0

    repo = run(
        [
            "gh",
            "repo",
            "view",
            "--json",
            "nameWithOwner",
            "--jq",
            ".nameWithOwner",
        ]
    )
    if repo.returncode != 0:
        system_message(
            f"Found PR {pr_url}, but could not resolve the repo to request Copilot review."
        )
        return 0

    name_with_owner = repo.stdout.strip()
    request = run(
        [
            "gh",
            "api",
            f"repos/{name_with_owner}/pulls/{pr_number}/requested_reviewers",
            "-X",
            "POST",
            "-f",
            "reviewers[]=copilot",
        ]
    )
    if request.returncode != 0:
        message = request.stderr.strip() or request.stdout.strip() or "unknown GitHub API error"
        system_message(
            f"Created PR {pr_url}, but requesting Copilot review failed: {message}"
        )
        return 0

    reviewers_after = get_requested_reviewers(pr_number)
    if "copilot" not in reviewers_after and "@copilot" not in reviewers_after:
        system_message(
            f"Created PR {pr_url}, attempted to request Copilot review, but GitHub did not show Copilot as a requested reviewer."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
