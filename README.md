# TATP-Study-1

Experiment control software for **TATP Study 1** (Touch Away The Pain). It runs one
three-hour laboratory session:
- it guides the experimenter and the participant through every phase;
- it presents the rating scales, and their training, on the participant's screen;
- it runs the two adaptive calibration procedures, for the pinprick F40 and the touch
  pressure;
- it commands the actuating garment;
- it times the heat-capsaicin sensitisation and the rekindle;
- it records everything to CSV files as it happens.

The thermode and the questionnaires (REDCap) are outside it.

It is a PySide6 (Qt) application with two windows on one Windows lab PC. The participant's
window is fullscreen on the HP display behind the curtain, and the experimenter's is on the
laptop's own display. Each participant makes three visits, one per touch condition, in a
counterbalanced order read from `config/allocation.csv`. The condition is recorded in the data
and never shown on either screen (`docs/SPEC.md` §16). Everything that varies is configuration
under `config/`, not code: timings, forces, pressures, thresholds, and every user-facing string
in Swedish and English.

A session runs against one of two garments, chosen in the launcher:
- **the mock garment**, which drives nothing and is what the tests use;
- **the prototype sleeve** (`arduino_mosfet`), which switches each channel on or off.

The driver for the valve garment is not written yet (`docs/STATUS.md`, "Later").

## If you are running sessions, read this first

**Experimenters are blind to the condition.** Read **[`SOP.md`](SOP.md)**, the standard
operating procedure. It says everything needed to run a session and nothing about the
conditions. Most of the rest of this repository describes the conditions, so do not open
`docs/SPEC.md`, `docs/LOG.md`, `docs/research/`, `config/` or `data/`, and do not open
**Design a pattern** in the launcher.

## Install

Follow **[`docs/SETUP.md`](docs/SETUP.md)**. It takes a LiU-managed Windows computer with no
administrator rights to a working conda environment, `tatp-study-1`, declared in
`environment.yml`. To add a dependency, edit `environment.yml` and run `make env`. Never use
`conda install` or `pip install`: an ad-hoc install is invisible in the diff and will not exist
on the lab PC.

On a machine where `make` cannot find `conda`, put its path in a gitignored `Makefile.local`,
for example `CONDA := /Users/you/miniconda3/bin/conda`.

## Run

**The launcher** is how experimenters start everything:

```
conda activate tatp-study-1
python run_session.py
```

It has four entries:
- **Run a session** checks the session details before anything starts. It refuses, for
  example, a code that is not in the allocation file, or a session that is already complete.
- **Instruments and environment** holds the filament weighing, and the room temperature and
  humidity.
- **Design a pattern** (`tools/design_pattern.py`) is for S only, because it shows the
  patterns' names and shapes.
- **Preview schedule** shows the session timeline and its warnings, in the experimenter's
  language.

**The command line** is for scripted and development runs:

```
conda run -n tatp-study-1 python run_session.py --participant 01 --session 1 --experimenter SM --patterns config/patterns/examples
```

It runs the same checks as the launcher.
- **Crashed session:** when an earlier run of the same session crashed, add `--resume` to
  continue it or `--new` to start it again.
- **Garment:** `--garment arduino_mosfet` picks the prototype sleeve.
- **Speed:** `--clock-speed` accelerates a development run, and the run is recorded as one.
- **Patterns:** `config/patterns/examples/` holds provisional mockups only (open item 5).

Both lab screens are 1920×1200. They are drawn at 1.5× (`screens.scale_factors` in
`config/hardware.yaml`), so both are 1280×800 to the software. That is the size every screen is
laid out, tested and approved at.

## The test gate

```
make check          # everything below, in parallel: the definition of done
make test           # the pytest suite only
make test-one ARGS="tests/test_touchcal.py -x"   # a targeted run
make validate       # the end-to-end validator only
make shots          # render every screen and compare it with its approved image
make preview        # print the session timeline and its warnings; starts nothing
```

`make check` must pass headless, with no hardware attached (`docs/SPEC.md` §17). It takes about
two to three minutes on the lab laptop, so use `make test-one` while developing. It runs:

- **the pytest suite**, including the no-literals check and the blinding text check
  (`tests/test_blinding_text.py`, against the list in `config/blinding.yaml`);
- **ruff**;
- **`tools/validate_session.py`**, which runs 18 whole sessions headless with the mock garment
  and the virtual participants and experimenters of `sim/`. It then checks the data files by
  name, against `docs/DATA_SCHEMA.md` and the timing rules;
- **`tools/shots.py`**, which renders every screen listed in `screenshots/manifest.yaml` and
  compares it with its approved image in `screenshots/reference/`. A screen changed on purpose
  is re-approved in the same commit, for example
  `make shots ARGS="--approve-matching 'experimenter_*'"`.

## Repository map

| Path | What it is |
|---|---|
| `run_session.py` | The entry point. With no session named it opens the launcher; with `--participant` it runs that session. |
| `tatp/launcher.py`, `tatp/instruments.py` | The launcher and its Instruments and environment dialog. |
| `tatp/session.py`, `tatp/session_runner.py` | Session state, and the whole session as an ordered list of stages. |
| `tatp/procedure.py`, `tatp/trials.py` | The shape every protocol takes (steps, interruptions, the experimenter's go), and the small trials built on it. |
| `tatp/preflight.py`, `tatp/resume.py` | The checks before a session starts, and crash recovery. |
| `tatp/pinprick.py` | Protocol A: the long and short pinprick protocols and the brush. |
| `tatp/touchcal.py`, `tatp/touchcal_maths.py` | Protocol B: the touch-pressure calibration. |
| `tatp/mapping.py` | Secondary-hyperalgesia area mapping and the distance ledger. |
| `tatp/setup_checks.py` | The audio masking check and the emergency-stop rehearsal. |
| `tatp/interruption.py` | Emergency stop, pause and resume. |
| `tatp/schedule.py`, `tatp/allocation.py` | The session timeline and its warnings, and the counterbalancing file. |
| `tatp/garment/` | The garment interface, the mock garment, the prototype sleeve (`arduino_mosfet.py`) and pattern loading. |
| `tatp/pattern_design.py` | The pattern designer's logic, without Qt. The window is `tools/design_pattern.py`. |
| `tatp/audio.py`, `tatp/responder.py`, `tatp/clock.py` | White noise, cues and alerts; the participant's remote; the session clock. |
| `tatp/ui/` | The participant window, the experimenter window, the VAS, shared widgets, and the application with its fonts and screen scaling. |
| `tatp/datafiles.py`, `tatp/provenance.py` | Every disk write, and what is recorded about the run. |
| `tatp/config.py`, `tatp/blinding.py` | Loading and checking the configuration, and the forbidden-terms check. |
| `tatp/screenshots.py` | The screen catalogue behind `make shots`. |
| `config/` | All configuration: `study1.yaml`, `hardware.yaml`, `schedule.yaml`, `filaments.yaml`, `allocation.csv`, `blinding.yaml`, `open_items.yaml`, the patterns and the text files. |
| `config/text/` | Every participant-facing and experimenter-facing string, in Swedish and English. |
| `tools/` | The validator, the screenshot tool, the schedule preview, the pattern designer, the allocation generator, the literals linter, the garment bit finder and the ethics-folder reader. |
| `sim/` | The virtual participants and experimenters the validator runs. |
| `tests/` | The pytest suite. |
| `screenshots/` | `manifest.yaml` and the approved reference images. |
| `fonts/` | The study fonts, installed by the software so that every machine draws the same letters. |
| `assets/` | The zone diagram (a placeholder, open item 11). |
| `docs/` | The working documents (below), plus `SETUP.md`, `DATA_SCHEMA.md`, `UI_PRINCIPLES.md`, the calibration analysis and `research/`. |
| `data/` | Session data. Gitignored, and never committed. |

## The working documents

Three documents, each with one job:

- **[`docs/SPEC.md`](docs/SPEC.md), the spec:** what the software must do. It is the
  authoritative specification.
- **[`docs/STATUS.md`](docs/STATUS.md), the status:** the current state and the next steps.
  It is rewritten each time, not appended to.
- **[`docs/LOG.md`](docs/LOG.md), the log:** implementation decisions, deviations from
  Bilaga 1, and anything else worth keeping. Decisions the spec did not settle link to a
  sourced report in [`docs/research/`](docs/research/README.md).

**What is waiting on S**, the values, wordings and decisions only S can supply, lives only in
**[`config/open_items.yaml`](config/open_items.yaml)**. It is machine-checked: every unresolved
item is printed when the software starts, and listed on the experimenter screen.

Before touching either calibration procedure, read `docs/calibration_methods_comparison.md`.
`CLAUDE.md` holds the working rules for Claude Code sessions on this repository.

## Data

Each session writes one CSV file per table (`docs/DATA_SCHEMA.md`) to `data/`, named
`TATP1_{YYYY-MM-DD_HH-MM-SS}_P{code}_S{session}_{table}.csv`. Every row is appended and flushed
as it is produced, and no file is ever overwritten. The files carry the participant code only.
They are transferred by hand to the LiU secure server (`SOP.md` §14).

## Licence

GPL-3.0 ([`LICENSE`](LICENSE)). The fonts under `fonts/` keep their own licences.
