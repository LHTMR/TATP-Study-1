"""The no-literals grep SPEC.md 4.2 and 17.2 ask for.

The scanner is `tools/lint_literals.py`; this is the gate that runs it. It is a test rather
than a lint rule because the thing it protects is a study property -- a threshold that lives in
code cannot be changed by S, does not appear in the data file's provenance, and is invisible to
anyone reviewing `config/`.

The rules themselves are tested against crafted source, not against the live package, so they
keep working whatever `tatp/` grows into. Decision 21 in PROGRESS.md: a test that asserts
today's state fails as a reward for progress.
"""

from __future__ import annotations

from tools.lint_literals import scan, scan_file


def _scan_source(tmp_path, source: str):
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return scan_file(path)


def test_the_package_has_no_literal_violations():
    violations, _ = scan()
    assert not violations, "SPEC.md 4.2:\n" + "\n".join(str(v) for v in violations)


def test_a_threshold_written_into_code_is_caught(tmp_path):
    violations, _ = _scan_source(tmp_path, "def f(p):\n    return p > 0.35\n")
    assert len(violations) == 1
    assert "0.35" in violations[0].message


def test_an_index_is_not_a_violation(tmp_path):
    violations, _ = _scan_source(tmp_path, "def f(xs):\n    return xs[3], xs[2:7]\n")
    assert not violations


def test_zero_and_one_are_not_violations(tmp_path):
    violations, _ = _scan_source(tmp_path, "def f(n):\n    return n - 1 if n > 0 else 1\n")
    assert not violations


def test_a_module_constant_is_allowed_and_inventoried(tmp_path):
    """The hole SPEC.md 4.2 opens for unit conversions, kept visible rather than silent."""
    violations, constants = _scan_source(tmp_path, "MN_PER_G = 9.80665\n")
    assert not violations
    assert len(constants) == 1
    assert "9.80665" in constants[0].message


def test_a_lowercase_module_assignment_is_still_a_violation(tmp_path):
    """Only an UPPER_SNAKE_CASE name earns the exemption -- otherwise it exempts everything."""
    violations, _ = _scan_source(tmp_path, "tap_max_s = 0.25\n")
    assert len(violations) == 1


def test_wording_written_into_a_qt_call_is_caught(tmp_path):
    violations, _ = _scan_source(tmp_path, "def f(w):\n    w.setText('Press the button')\n")
    assert len(violations) == 1
    assert "setText" in violations[0].message


def test_a_config_key_passed_to_a_text_setter_is_still_caught(tmp_path):
    """Deliberate: a key and a sentence are indistinguishable at the call site.

    `setText(text['welcome'])` is the shape that passes, and it is the shape that is correct --
    the string arrives from config/text/ rather than being written here.
    """
    violations, _ = _scan_source(tmp_path, "def f(w):\n    w.setText('welcome')\n")
    assert len(violations) == 1


def test_a_string_from_config_is_not_a_violation(tmp_path):
    violations, _ = _scan_source(tmp_path, "def f(w, text):\n    w.setText(text['welcome'])\n")
    assert not violations
