"""The no-literals grep of SPEC.md 4.2 and 17.2.

"No timings, forces, pressures, thresholds, rates or participant-facing strings in `.py`
files." A grep cannot tell a threshold from an array index, so this walks the AST instead and
applies two rules that can be stated exactly:

**Numbers.** Every numeric literal under `tatp/` is a violation unless it is

- `0`, `1`, `-1` or `2` -- identity, an index, an off-by-one, a midpoint. No study parameter
  is one of these in a way that would matter, and requiring `width / TWO` would be worse than
  the rule it enforces;
- inside a subscript, which is an index whatever its value;
- the value of an assignment in a module body (`UPPER_SNAKE_CASE` only) or a class body
  (any name, because SPEC.md 12.1 has each driver *declare* its capabilities -- `n_channels`
  is a fact about the hardware and belongs with the class that speaks to it).

Those last two are a deliberate hole, and the first is the one SPEC.md 4.2 opens itself when
it allows a unit conversion. What the hole buys is that the value has a name and sits at the
top of a scope, where it is greppable, rather than appearing mid-expression. `--inventory`
prints every one of them so it stays visible instead of being taken on trust: a study
parameter appearing in that list is a violation the review has to catch, and reading twenty
named constants is a thing a person can actually do.

**Strings.** A string literal handed to a Qt text setter is a violation without exception.
That is the failure mode the rule exists for -- participant-facing wording living in code
where neither the ethics attachments nor the Swedish review can reach it. Docstrings, assert
messages, config keys and log event names are not text a participant or an experimenter ever
reads, so they are not touched.

Run it directly to see what it finds:

    conda run -n tatp-study-1 python tools/lint_literals.py --inventory
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "tatp"

# Numbers that cannot be a study parameter whatever the surrounding expression.
ALLOWED_NUMBERS = (0, 1, -1, 2)

# How many distinct values to show per declaration in `--inventory` before summarising.
INVENTORY_VALUES = 8

# Qt's text setters. A string reaching one of these is rendered to a screen.
TEXT_SETTERS = frozenset(
    {
        "setText",
        "setPlainText",
        "setHtml",
        "setTitle",
        "setToolTip",
        "setWindowTitle",
        "setPlaceholderText",
        "addItem",
        "setItemText",
    }
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


class _Scanner(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.violations: list[Finding] = []
        self.constants: list[Finding] = []
        self._allowed_lines: set[int] = set()

    # -- declarations at the top of a scope ---------------------------------------------

    def scan(self, tree: ast.Module) -> None:
        self._declarations(tree.body, require_upper=True)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._declarations(node.body, require_upper=False)
        self.visit(tree)

    def _declarations(self, body: list[ast.stmt], require_upper: bool) -> None:
        for node in body:
            names = [t.id for t in _assignment_targets(node) if isinstance(t, ast.Name)]
            if not names or (require_upper and not all(name.isupper() for name in names)):
                continue
            numbers = _numbers_in(node)
            for number in numbers:
                self._allowed_lines.add(id(number))
            if not numbers:
                continue
            # One line per declaration, not per number. A validation table like config.SCHEMA
            # holds a hundred bounds, and listing them one by one buries the handful of
            # constants the inventory exists to show.
            values = sorted({number.value for number in numbers}, key=repr)
            shown = ", ".join(repr(value) for value in values[:INVENTORY_VALUES])
            if len(values) > INVENTORY_VALUES:
                shown += f", … ({len(values)} distinct values)"
            self.constants.append(
                Finding(self.path, node.lineno, f"{', '.join(names)} = {shown}")
            )

    # -- numbers -----------------------------------------------------------------------

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # An index is an index whatever its value, so only the indexed object is scanned.
        for number in _numbers_in(node.slice):
            self._allowed_lines.add(id(number))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if id(node) in self._allowed_lines:
            return
        if isinstance(node.value, bool):
            return
        if isinstance(node.value, (int, float)) and node.value not in ALLOWED_NUMBERS:
            self.violations.append(
                Finding(
                    self.path,
                    node.lineno,
                    f"numeric literal {node.value!r}. Study parameters live in config/; "
                    "a genuine unit conversion goes in an UPPER_SNAKE_CASE module constant",
                )
            )

    # -- strings -----------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        attr = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if attr in TEXT_SETTERS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value:
                    self.violations.append(
                        Finding(
                            self.path,
                            arg.lineno,
                            f"{attr}({arg.value!r}) renders a string written in code. "
                            "User-facing wording lives in config/text/",
                        )
                    )
        self.generic_visit(node)


def _assignment_targets(node: ast.stmt) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def _numbers_in(node: ast.AST) -> list[ast.Constant]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, (int, float))
        and not isinstance(child.value, bool)
    ]


def scan_file(path: Path) -> tuple[list[Finding], list[Finding]]:
    scanner = _Scanner(path)
    scanner.scan(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return scanner.violations, scanner.constants


def scan(root: Path = PACKAGE_DIR) -> tuple[list[Finding], list[Finding]]:
    """Return (violations, named constants) for every module under `root`."""
    paths = sorted(root.rglob("*.py"))
    assert paths, f"no Python files under {root}"
    violations: list[Finding] = []
    constants: list[Finding] = []
    for path in paths:
        found, named = scan_file(path)
        violations.extend(found)
        constants.extend(named)
    return violations, constants


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="also list every module-level numeric constant, so the allowed hole stays visible",
    )
    args = parser.parse_args()

    violations, constants = scan()
    if args.inventory:
        print(f"{len(constants)} numeric declarations under {PACKAGE_DIR.name}/:")
        for constant in constants:
            print(f"  {constant}")
        print()
    for violation in violations:
        print(violation)
    print(f"{len(violations)} literal violations.")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
