#!/usr/bin/env python3
"""PreToolUse hook: reject unsafe Bash calls before they run.

Two things permission patterns cannot reliably catch, which is why this exists:

1. Compound commands. Permission rules match the command string, so `pytest && rm -rf data`
   can satisfy a rule written for `pytest`. Refusing shell operators outright removes the
   whole class of bypass, and one command per call is easy to comply with.
2. Paths outside the repository. A relative path cannot escape far, but an absolute path or a
   `~` can reach the user's OneDrive, which holds documents that are expensive to lose.

Contract (https://code.claude.com/docs/en/hooks): the tool call arrives as JSON on stdin.
Exit 2 blocks the call and returns stderr to the model. Exit 0 with no output means no
decision, and the normal permission rules apply.

Deliberate false positives: a shell operator inside a quoted string is still refused, because
distinguishing them requires parsing the shell and getting that wrong fails open. Splitting
the command is always an available fix.
"""

import json
import os
import re
import sys

# Shell metacharacters that allow more than one command in a single call.
OPERATORS = [
    ("&&", "&&"),
    ("||", "||"),
    (";", ";"),
    ("|", "|"),
    ("$(", "$(...)"),
    ("`", "backtick"),
    ("\n", "newline"),
]

# Absolute or home-relative paths appearing as whitespace-delimited tokens, with any
# surrounding quotes stripped.
PATH_TOKEN = re.compile(r"""(?:^|[\s=])['"]?(~[^\s'"]*|/[^\s'"]+)""")


def fail(message: str) -> None:
    print(f"Blocked by .claude/hooks/check_bash.py: {message}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        sys.exit(0)

    for token, label in OPERATORS:
        if token in command:
            fail(
                f"the command contains {label!r}, so it may run more than one thing. "
                "Issue one shell command per Bash call."
            )

    # Resolve the project root from the hook's own location rather than from cwd, which the
    # command itself could have changed.
    project_root = os.path.realpath(
        os.environ.get(
            "CLAUDE_PROJECT_DIR",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."),
        )
    )

    for match in PATH_TOKEN.finditer(command):
        raw = match.group(1)
        resolved = os.path.realpath(os.path.expanduser(raw))
        if os.path.commonpath([resolved, project_root]) != project_root:
            fail(
                f"the path {raw!r} resolves to {resolved!r}, which is outside the repository "
                f"({project_root}). Work only inside the repository."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
