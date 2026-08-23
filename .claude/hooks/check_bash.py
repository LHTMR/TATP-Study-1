#!/usr/bin/env python3
"""PreToolUse hook: reject unsafe Bash calls before they run.

Two things permission patterns cannot reliably catch, which is why this exists:

1. Compound commands. Permission rules match the command string, so `pytest && rm -rf data`
   can satisfy a rule written for `pytest`. Refusing shell operators outright removes the
   whole class of bypass, and one command per call is easy to comply with.
2. Paths outside the repository, whether absolute, `~`-relative or reached by `..`. This is what
   lets `tools/*` be an allow rule: the scripts there take path arguments, and without this the
   permission rule would have to forbid arguments altogether to stop `--out ../../elsewhere`.

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

# Every whitespace- or `=`-delimited token, with any surrounding quotes stripped. Each is
# treated as a candidate path: a token that is not one (`conda`, `run`, `main`) resolves inside
# the repository and passes, so checking everything costs nothing and misses nothing.
PATH_TOKEN = re.compile(r"""(?:^|[\s=])['"]?([^\s'"=]+)""")


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

    # Relative tokens are resolved against the directory the command will actually run in.
    cwd = payload.get("cwd") or project_root

    for match in PATH_TOKEN.finditer(command):
        raw = match.group(1)
        # A leading `-` marks a flag rather than a path. `--out=../elsewhere` still reaches the
        # check, because the token pattern breaks on `=`.
        if raw.startswith("-"):
            continue
        expanded = os.path.expanduser(raw)
        resolved = os.path.realpath(
            expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)
        )
        if os.path.commonpath([resolved, project_root]) != project_root:
            fail(
                f"the path {raw!r} resolves to {resolved!r}, which is outside the repository "
                f"({project_root}). Work only inside the repository."
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
