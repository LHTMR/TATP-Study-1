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

.PHONY: check test lint

check: test lint
	@echo
	@echo "INCOMPLETE GATE: validate and shots are Milestone 2 and are not run yet."

test:
	$(CONDA_RUN) python -m pytest -q

lint:
	$(CONDA_RUN) python -m ruff check .
