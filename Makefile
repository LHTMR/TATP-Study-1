# TATP Study 1. See CLAUDE.md for the commands and why they are shaped this way.
#
# Every recipe goes through `conda run`, so the targets work whether or not the environment is
# active. Recipes are spawned through /bin/sh, which does not define the `conda` shell function,
# so `conda` here is always the binary on PATH.
#
# `check` is the gate. It is NOT complete yet: the end-to-end validator
# (tools/validate_session.py, SPEC.md 17.3) does not exist, so `check` runs the unit tests, the
# linter and the screenshot comparison. It says so when it runs, rather than letting a partial
# gate look like a passing one.

# `conda` is whatever is on PATH, which is right on the lab PC and in any normal shell. Some
# shells -- the Claude Code app's, on this Mac -- run with a minimal PATH that has no conda
# directory in it, and then every target here fails with "conda: No such file or directory".
# Override CONDA in Makefile.local rather than editing this line: that file is gitignored, so a
# machine-specific absolute path stays on the machine it describes and never reaches the lab PC.
#
#   echo 'CONDA := /Users/you/miniconda3/bin/conda' > Makefile.local
CONDA ?= conda
-include Makefile.local

CONDA_RUN := $(CONDA) run --no-capture-output -n tatp-study-1

.PHONY: check test test-one lint literals shots preview

check: test lint shots
	@echo
	@echo "INCOMPLETE GATE: the end-to-end validator (make validate) is not built yet."

test:
	$(CONDA_RUN) python -m pytest -q

# One file, one test, or any other pytest arguments, without leaving the environment:
#   make test-one ARGS="tests/test_touchcal.py -x --timeout=30"
# It exists so that a targeted run is still a `make` target. The `conda run` line above is the
# only place the environment is named, and a target is one allow-list entry rather than one per
# spelling of the same conda command (CLAUDE.md, "write the command so the rule can match it").
test-one:
	$(CONDA_RUN) python -m pytest $(ARGS)

lint:
	$(CONDA_RUN) python -m ruff check .

# The SPEC.md 4.2 literals inventory. The violations are already a test (tests/test_no_literals.py,
# so `make check` covers them); this target is for reading the list of named constants the rule
# lets through, which is the part that needs a human eye rather than an assertion.
literals:
	$(CONDA_RUN) python tools/lint_literals.py --inventory

# Screen states as PNGs, compared against the approved references (SPEC.md 17.4). The bare
# target is the gate's form: write every screen, compare the armed ones, fail on a difference.
#   make shots ARGS="--write-manifest"        after adding or removing a screen
#   make shots ARGS="--approve-all"           a wording pass across every screen
#   make shots ARGS="--approve NAME"          arm one screen
#   make shots ARGS="--freeze"                require every screen approved and clean
shots:
	$(CONDA_RUN) python tools/shots.py $(ARGS)

# The session timeline and its warnings (SPEC.md 7.2). No hardware, nothing written.
#   make preview ARGS="--start 09:30"
preview:
	$(CONDA_RUN) python tools/preview_schedule.py $(ARGS)
