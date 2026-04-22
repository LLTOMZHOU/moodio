#!/usr/bin/env python3
"""Request Codex review after a local `gh pr create`."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from typing import Any


COMMENT_BODY = (
    "@codex review for correctness, API/server contract issues, "
    "risky assumptions, and regressions."
)
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


def system_message(message: str) -> None:
    print(json.dumps({"systemMessage": message}))


def has_existing_codex_request(pr_number: int) -> bool:
    payload = run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "comments",
        ]
    )
    for comment in payload.get("comments", []):
        if not isinstance(comment, dict):
            continue
        body = comment.get("body")
        if isinstance(body, str) and "@codex review" in body.lower():
            return True
    return False


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
            "number,url",
        ]
    )
    if pr_view.returncode != 0:
        system_message(
            "Detected `gh pr create`, but could not find the current branch PR to request Codex review."
        )
        return 0

    pr_payload = json.loads(pr_view.stdout)
    pr_number = pr_payload["number"]
    pr_url = pr_payload["url"]

    if has_existing_codex_request(pr_number):
        return 0

    comment = run(
        [
            "gh",
            "pr",
            "comment",
            str(pr_number),
            "--body",
            COMMENT_BODY,
        ]
    )
    if comment.returncode != 0:
        message = comment.stderr.strip() or comment.stdout.strip() or "unknown gh error"
        system_message(
            f"Created PR {pr_url}, but posting `@codex review` failed: {message}"
        )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
