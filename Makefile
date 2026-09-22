# TATP Study 1. See CLAUDE.md for the commands and why they are shaped this way.
#
# Every recipe goes through `conda run`, so the targets work whether or not the environment is
# active. Recipes are spawned through /bin/sh, which does not define the `conda` shell function,
# so `conda` here is always the binary on PATH.
#
# `check` is the gate (SPEC.md 17.1): unit tests, linter, end-to-end validator, screenshots.
# Every stage runs even when an earlier one fails, and the last line names every stage that
# failed -- "exits non-zero listing every failure" -- rather than stopping at the first.
# The validator reports the SPEC.md 17.3 assertions it cannot make yet as skipped, and counts
# them, so a green gate says how much of it is still waiting on later milestones.

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

.PHONY: check test test-one lint validate literals shots layouts archive preview ethics calibration-sim

GATE_STAGES := test lint validate shots

check:
	@failed=""; \
	for stage in $(GATE_STAGES); do \
		$(MAKE) --no-print-directory $$stage || failed="$$failed $$stage"; \
	done; \
	if [ -n "$$failed" ]; then echo; echo "GATE FAILED:$$failed"; exit 1; fi; \
	echo; echo "GATE PASSED: $(GATE_STAGES)"

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

# The slice run twice headless with one seed, then its data files checked (SPEC.md 17.3).
# Writes to data/_validate/, which it clears first.
validate:
	$(CONDA_RUN) python tools/validate_session.py $(ARGS)

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
#   make shots ARGS="--approve-matching 'participant_*'"   arm one role's screens
#   make shots ARGS="--freeze"                require every screen approved and clean
shots:
	$(CONDA_RUN) python tools/shots.py $(ARGS)

# Every VAS scale in each anchor layout -- the study's, and the alternative S keeps to show
# colleagues. Writes to screenshots/vas_layouts/, which is not compared against anything.
layouts:
	$(CONDA_RUN) python tools/vas_layouts.py

# File a folder of renders under screenshots/archive/, dated by the newest file in it. Only for
# renders nothing can produce again -- regenerable folders are refused, re-render those instead.
#   make archive ARGS="tick_variants"
archive:
	$(CONDA_RUN) python tools/archive_screens.py $(ARGS)

# The ethics folder reader (.claude/skills/ethics-folder). Read-only, and nothing it prints is
# written anywhere. A target rather than a bare command because the folder lives outside the
# repository, so only the Makefile's CONDA knows how to reach an interpreter -- an app shell with
# no conda on PATH cannot run tools/read_ethics.py any other way.
#   make ethics ARGS="--list"
#   make ethics ARGS="Bilaga1_Forskningsplan_V2.docx --grep anchor --context 3"
ethics:
	$(CONDA_RUN) python tools/read_ethics.py $(ARGS)

# The calibration simulation behind docs/calibration_methods_comparison.md. Takes a couple of
# minutes and writes nothing -- it prints the tables in that document, so the numbers there can
# be reproduced rather than taken on trust. A target because the file sits in docs/ and is not
# one of the `python tools/...` forms the permission rules match, so there is no other way to
# run it from an agent session. Do not tidy the file it runs (docs/LOG.md N6.8).
calibration-sim:
	$(CONDA_RUN) python docs/calibration_sim.py

# The session timeline and its warnings (SPEC.md 7.2). No hardware, nothing written.
#   make preview ARGS="--start 09:30"
preview:
	$(CONDA_RUN) python tools/preview_schedule.py $(ARGS)
