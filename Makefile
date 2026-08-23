# TATP Study 1. See CLAUDE.md for the commands and why they are shaped this way.
#
# Every recipe goes through `conda run`, so the targets work whether or not the environment is
# active. Recipes are spawned through /bin/sh, which does not define the `conda` shell function,
# so `conda` here is always the binary on PATH.
#
# `check` is the gate. It is NOT complete yet: the end-to-end validator (tools/validate_session.py)
# and the screenshot comparison (tools/check.py, SPEC.md 17.4) are Milestone 2 and do not exist,
# so `check` currently runs the unit tests and the linter only. It says so when it runs, rather
# than letting a partial gate look like a passing one.

CONDA_RUN := conda run --no-capture-output -n tatp-study-1

.PHONY: check test test-one lint preview

check: test lint
	@echo
	@echo "INCOMPLETE GATE: validate and shots are Milestone 2 and are not run yet."

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

# The session timeline and its warnings (SPEC.md 7.2). No hardware, nothing written.
#   make preview ARGS="--start 09:30"
preview:
	$(CONDA_RUN) python tools/preview_schedule.py $(ARGS)
