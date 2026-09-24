# TATP-Study-1

Experiment control software for **TATP Study 1** (Touch Away The Pain). It runs one
three-hour laboratory session: it guides the experimenter and the participant through every
phase, presents the rating scales on the participant's screen, runs the two adaptive calibration
procedures (the pinprick F40 calibration and the touch-pressure calibration), commands the
actuating garment, times the heat-capsaicin sensitisation and the rekindle, and records
everything to CSV files as it happens. The thermode and the questionnaires (REDCap) are outside
it.

It is a PySide6 (Qt) application with two windows on one Windows lab PC: a fullscreen participant
window behind the curtain and an experimenter window on the lab display. Each participant makes
three visits, each with one of three touch conditions in a counterbalanced order read from
`config/allocation.csv`. The condition is recorded in the data and never shown on either screen
(`docs/SPEC.md` §16). Everything that varies — timings, forces, pressures, thresholds and every
user-facing string in Swedish and English — is configuration under `config/`, not code. Until
the real garment drivers exist, sessions run against the mock garment.

## Install

Follow **[`docs/SETUP.md`](docs/SETUP.md)**. It takes a LiU-managed Windows computer with no
administrator rights to a working conda environment, `tatp-study-1`, declared in
`environment.yml`. Add a dependency by editing `environment.yml` and running `make env`. Never
`conda install` or `pip install`.

## Run

**The launcher**, for experimenters:

```
conda activate tatp-study-1
python run_session.py
```

It offers four entries: **Run a session**, **Instruments and environment** (filament weighing,
room temperature and humidity), **Design a pattern** (`tools/design_pattern.py`, for S only,
because it shows pattern names and shapes) and **Preview schedule**.

**The command line**, for scripted runs:

```
conda run -n tatp-study-1 python run_session.py --participant 01 --session 1 --experimenter SM --patterns config/patterns/examples
```

It runs the same preflight checks as the launcher. Add `--resume` or `--new` when a crashed
session is found, and `--clock-speed` for an accelerated development run (it is recorded as one).
`config/patterns/examples/` holds provisional mockups only (open item 5).

**How to run a session in the lab** is in **[`SOP.md`](SOP.md)**, the standard operating procedure
for experimenters. It deliberately says nothing about the conditions.

Other commands:

```
make preview        # the session timeline and its warnings; starts nothing
make check          # the gate (below)
```

## The test gate

```
make check          # unit tests, ruff, the end-to-end validator and the screenshot comparison
make test           # unit tests only
make test-one ARGS="tests/test_touchcal.py -x"   # a targeted run
make validate       # the end-to-end validator only
make shots          # render every screen and compare against the approved references
```

`make check` is the definition of done (`docs/SPEC.md` §17, §21). It must pass headless with no
hardware attached. It runs:

- the pytest suite, including the no-literals check and the blinding text check
  (`tests/test_blinding_text.py`, against the list in `config/blinding.yaml`);
- `tools/validate_session.py`, which runs whole sessions headless with the mock garment and the
  virtual participants and experimenters of `sim/`, then asserts against the data files and
  `docs/DATA_SCHEMA.md`;
- `tools/shots.py`, which renders every screen listed in `screenshots/manifest.yaml` and compares
  it with its approved image in `screenshots/reference/`. A deliberately changed screen must be
  re-approved in the same commit (`make shots ARGS="--approve-matching 'experimenter_*'"`).

It takes several minutes on the lab PC, so use `make test-one` while developing.

## Repository map

| Path | What it is |
|---|---|
| `run_session.py` | Entry point. With no session named it opens the launcher; with `--participant` it runs that session. |
| `tatp/` | The package. |
| `tatp/launcher.py`, `tatp/instruments.py` | The launcher and its Instruments and environment dialog. |
| `tatp/session.py`, `tatp/session_runner.py` | Session state, and the whole session as an ordered list of stages. |
| `tatp/preflight.py`, `tatp/resume.py` | The checks before a session starts, and crash recovery. |
| `tatp/pinprick.py` | Protocol A: the long and short pinprick protocols and the brush. |
| `tatp/touchcal.py`, `tatp/touchcal_maths.py` | Protocol B: the touch-pressure calibration. |
| `tatp/mapping.py` | Secondary-hyperalgesia area mapping and the distance ledger. |
| `tatp/setup_checks.py` | The audio masking check and the emergency-stop rehearsal. |
| `tatp/interruption.py` | Emergency stop, pause and resume. |
| `tatp/schedule.py`, `tatp/allocation.py` | The session timeline, and the counterbalancing file. |
| `tatp/garment/` | The garment interface, the mock driver and pattern loading. |
| `tatp/ui/` | The participant window, the experimenter window, the VAS and shared widgets. |
| `tatp/datafiles.py`, `tatp/provenance.py` | Every disk write, and what is recorded about the run. |
| `tatp/screenshots.py` | The screen catalogue behind `make shots`. |
| `config/` | All configuration: `study1.yaml`, `hardware.yaml`, `schedule.yaml`, `filaments.yaml`, `allocation.csv`, `blinding.yaml`, `open_items.yaml`, the patterns and the text files. |
| `config/text/` | Every participant-facing and experimenter-facing string, Swedish and English. |
| `tools/` | The validator, the screenshot tool, the schedule preview, the allocation generator, the literals linter and the ethics-folder reader. |
| `sim/` | Virtual participants and experimenters for the validator. |
| `tests/` | The pytest suite. |
| `screenshots/` | `manifest.yaml` and the approved reference images. |
| `assets/` | The zone diagram (a placeholder, open item 11). |
| `docs/` | The working documents (below), `SETUP.md`, `DATA_SCHEMA.md`, `UI_PRINCIPLES.md`, the calibration analysis and `research/`. |
| `data/` | Session data. Gitignored, and never committed. |

## The working documents

Three documents, each with one job:

- **[`docs/SPEC.md`](docs/SPEC.md), the spec.** What the software must do. It is the
  authoritative specification, and describes the conditions (§12.2, §16).
- **[`docs/STATUS.md`](docs/STATUS.md), the status.** The current state and the next steps. It
  is rewritten, not appended to.
- **[`docs/LOG.md`](docs/LOG.md), the log.** Implementation decisions, deviations from Bilaga 1
  and anything else worth keeping.

**What is waiting on S** — values, wordings and decisions only S can supply — lives only in
**[`config/open_items.yaml`](config/open_items.yaml)**. It is machine-checked: every unresolved
item is printed when the software starts and listed on the experimenter screen.

Before touching either calibration procedure, read `docs/calibration_methods_comparison.md`.
`CLAUDE.md` holds the working rules for Claude Code sessions on this repository.

## Data

Each session writes one CSV file per table (`docs/DATA_SCHEMA.md`) to `data/`, named
`TATP1_{YYYY-MM-DD_HH-MM-SS}_P{code}_S{session}_{table}.csv`. Every row is appended and flushed as
it is produced, and no file is ever overwritten. The files carry the participant code only. They
are transferred manually to the LiU secure server (`SOP.md` §14).

## Licence

GPL-3.0.
