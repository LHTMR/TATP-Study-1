# PROGRESS

Handover file (CLAUDE.md). Between `docs/SPEC.md`, this file, `FOR_S.md` and the git log, a
fresh session should need nothing from any previous conversation.

Everything waiting on S — values, wordings, reviews, decisions — is in **`FOR_S.md`**, not
here. Keep the two updated together.

**Last updated:** 23 August 2026, session 5.
**Milestone:** 1 (the vertical slice) — *in progress.*

**Session 5 ran the code for the first time and built most of Milestone 1's foundation.**
Everything written in session 1 had been written and never executed; that is no longer true.
The config layer, the allocation reader, the clock and provenance all run. The data-file
writer, the garment layer, the responder, the VAS and the session are new, and there are 118
tests and a `make` gate. Six commits, each with the suite passing.

---

## Read this first

**`make check` exists and passes, but it is not the whole gate yet.** It runs the unit tests
and the linter. The end-to-end validator and the screenshot comparison are Milestone 2 and do
not exist, so the target prints a line saying so rather than letting a partial gate look like a
passing one. Finish it in Milestone 2 and delete that line.

```
make check
```

---

## Environment

`tatp-study-1` was created on this machine and verified: PySide6 6.11.2, Qt 6.11.2, and
`QWidget.grab()` returns a correctly-sized pixmap under `QT_QPA_PLATFORM=offscreen`. So the
headless screenshot approach in SPEC.md 17.4 is sound on this platform.

**One change to `environment.yml`:** `sounddevice` → `python-sounddevice`. The conda-forge
package name differs from the import name and the original spelling does not resolve on any
channel, so `conda env create` failed outright. The import name in Python is still
`sounddevice`.

Note the base conda is **osx-64**, so the env is Intel/Rosetta on this Mac. Harmless here;
irrelevant to the Windows lab PC.

**The `conda` shell function was broken in session 5's shell** — `CONDA_EXE` was unset, so
`conda run …` exited 126 with "permission denied". The binary on `PATH` is fine, so
`command conda run …` worked and was used until the Makefile existed. **Use `make` and the
problem does not arise**: `make` spawns its recipes through `/bin/sh`, which never defines the
function. Do not "fix" anything in the repository for this.

---

## What exists

| File | State |
|---|---|
| `docs/DATA_SCHEMA.md` | **Complete**, and now genuinely parsed by `tatp/datafiles.py` |
| `config/*.yaml` | All load and validate. `config/allocation.csv` is generated and committed |
| `tatp/config.py` | Runs. Load, validate against `SCHEMA`, cross-check language key sets, open items |
| `tatp/allocation.py` | Runs. Balance verified against the committed file |
| `tatp/clock.py` | Runs, including the accelerated mode SPEC.md 17.3 needs |
| `tatp/provenance.py` | Runs. Every field populated for real |
| `tatp/datafiles.py` | **New.** Schema-driven writer, open-append-close per row |
| `tatp/garment/base.py` | **New.** Ceiling, rate limit, command recording, pattern playback, looping |
| `tatp/garment/mock.py` | **New.** Full driver with fault injection |
| `tatp/garment/patterns.py` | **New.** Tick-grid loader and event expansion |
| `tatp/responder.py` | **New.** R400 key mapping, with the `escape` rule machine-checked |
| `tatp/ui/vas.py` | **New.** `VasState` (no Qt, all the behaviour) and `VasWidget` |
| `tatp/session.py` | **New.** Session state, all 40 provenance keys, the log, blinding |
| `tools/make_allocation.py` | Run once; the output is committed |
| `Makefile` | **New.** `check`, `test`, `lint`. `check` is not yet the whole gate |
| `tests/` | 118 tests, all passing headless |

## What does not exist yet

`tatp/schedule.py`, `audio.py`, `screenshots.py`, `tatp/ui/{participant,experimenter,widgets}.py`,
`tatp/garment/arduino_{mosfet,valves}.py`, `pinprick.py`, `touchcal.py`, `instruments.py`,
`launcher.py`, `run_session.py`, `tools/` (except `make_allocation.py`), `sim/`, `README`,
`SOP.md`, `HARDWARE_BRINGUP.md`.

---

## Decisions taken, not already in SPEC.md

Items 1–8 were taken in session 1 and are unchanged; 9–13 are session 5.

1. **`docs/DATA_SCHEMA.md` is parsed, not just read.** It declares a parsing contract: a
   `### table_name` heading followed by a table with the header
   `| Column | Type | Unit | Required | Description |`. `tatp/datafiles.py` reads it and
   `tools/validate_session.py` will, so the writer and the validator cannot drift from the
   documentation. Edit the markdown and both follow. **This is the reason not to reformat
   those tables casually.**

2. **`config/open_items.yaml` is the SPEC.md 20 mechanism.** Each item names a dotted config
   path in `resolved_when:`; the loader warns for every path that is still null. Adding an open
   item means adding a row there, not code.

3. **Four locally-raised open items (`L1`–`L4`)**, for values the spec *requires to exist* but
   does not fix: the software pressure ceiling (200 kPa is a working value, not an agreed
   limit), the pressure rate limit (60 kPa/s), audio levels in dBFS, and the participant screen
   text. All in `FOR_S.md`.

4. **Participant screen text is a placeholder, deliberately.** Every such string begins
   `PLACEHOLDER`, `Config.has_placeholder_text()` detects them, and the experimenter screen is
   to carry an unmissable banner while any remain. **This is the main thing S needs to supply.**

5. **Experimenter Swedish was written from scratch** (`experimenter_sv.yaml`). Not
   ethics-bound and not participant-facing, so it did not need to be sourced. Worth a read.

6. **Allocation design.** Condition order drawn from a pool holding each of the 6 permutations
   equally often. Starting limb alternates by participant *index*, which balances 21/20 exactly
   where random assignment would not. Codes `01`–`41`, seed `20260823` recorded in a `#` header
   line inside the CSV. Now generated, committed and covered by tests.

7. **`static_sham` pattern** holds all five channels on, so the sham matches the moving patterns
   in spatial extent and differs only in motion. **Assumption — confirm at bring-up.**

8. **Permissions and `CLAUDE.md` tightened** (see the git log): the bypass class is denied,
   because each of `find`, `sed`, `bash -c` and the rest is a way to run something the deny list
   would otherwise have caught. The one remaining hole is stated in `FOR_S.md` B5.3.

9. **`play_pattern` takes no `params` dict**, though SPEC.md 12.1's signature has one. Every
   per-pattern parameter the spec names — row interval, channel ids, loop — lives in the
   pattern's sidecar YAML, so `params` would be an option nothing reads, which CLAUDE.md
   forbids. The docstring in `tatp/garment/base.py` says so. **In `FOR_S.md` B1.5 for review.**

10. **The clamps live in the base class, not the drivers.** SPEC.md 12.1 lists `set_pressure`
    as "clamped to the configured ceiling" per driver. A clamp implemented per driver is a
    clamp that differs per driver, so the ceiling, the rate limit, command recording and
    pattern playback are all in `GarmentController` and a driver implements device I/O only.

11. **The rate limit does not apply to the first command to a channel, nor to `stop()`.** It
    constrains change over elapsed time, and the first command has no interval to constrain.
    SPEC.md 13's purpose is that holding a button cannot ramp to maximum quickly, not that a
    single deliberate command to a calibrated pressure is slowed. `stop()` must never be slowed.

12. **Pattern looping lives in the base class and wraps elapsed time** rather than resetting it,
    so a slow tick resumes at the right point in the cycle instead of dropping a whole cycle.
    At exactly `t = duration_s` the next cycle's first row has already begun — that is correct,
    and there is a test that pins it.

13. **`docs/calibration_sim.py` is excluded from ruff** rather than reformatted. It is the
    record of the simulation behind `docs/calibration_methods_comparison.md` and the numbers
    there should stay traceable to the code as it was run.

14. **The VAS splits into `VasState` and `VasWidget`**, in the one file `SPEC.md` §4 gives it.
    The state imports no Qt and holds all the behaviour, so every rule in SPEC.md 10.2 is
    tested directly instead of through a widget.

15. **The first VAS press has a direction even though it does not move the marker**, so
    pressing the other button next counts as a direction change. SPEC.md 10.2 does not say
    which way to read this. A test pins the reading.

16. **A confirm with no marker shown produces no response.** There is nothing to record, so
    `VasWidget` emits `pressed_without_marker` and the session logs the press instead.

17. **`Session.experimenter_view()` is the only thing the experimenter screen may show.** The
    blinding rule then has a test on it rather than depending on care at each call site.

18. **The RNG seed is drawn when not supplied, and recorded either way**, so a session is
    reproducible from its own data file. Defaulting it to a constant would make every session's
    randomisation identical.

19. **`Session` takes the pattern folder as an argument with no default.** The experimenter
    selects it (SPEC.md 12.2), and defaulting to `config/patterns/examples/` would quietly
    substitute the provisional mockups for the real patterns (open item 5).

---

## What session 5 fixed

- **Two config files did not parse.** `config/open_items.yaml` and
  `config/text/experimenter_en.yaml` had prose values containing an unquoted `key: value`,
  which YAML reads as a nested mapping. The Swedish experimenter file quotes the same four
  strings; the English one had lost the quotes. `tests/test_config_files.py` now parses every
  YAML file under `config/`, including the pattern sidecars that `config.load` never touches.
- **The last stray tooling artefact from session 1** — an `</invoke>` tag on the final line of
  `docs/DATA_SCHEMA.md`. A search across the tracked text files shows no others remain.
- **`config/allocation.csv` generated and committed**, which unblocked config loading. This
  closes SPEC.md 20 item 10.
- **ruff made clean** across the repository.

---

## Next steps, in order

The foundation is done: config, allocation, clock, provenance, data files, garment, responder,
VAS and session all run and are tested. What is left of Milestone 1 is the phases on top of
them and the two windows.

1. **`tatp/ui/participant.py`** — the fullscreen participant window, holding the VAS widget and
   the standby/instruction screens. Every string from `participant_*.yaml`; all of them are
   still `PLACEHOLDER`, which is expected (`FOR_S.md` A1.1).
2. **`tatp/ui/experimenter.py`** — SPEC.md 11. Build it against `Session.experimenter_view()`,
   which is the only thing it may show. It must carry the unmissable banner while
   `placeholder_text` is true, and a second one for a reduced-capability device (SPEC.md 12.4).
3. **The thin path itself** — a three-application calibration, one pinprick trial, one touch
   rating, driven through the session. Keep the long protocol's search/bracket/cap logic for
   Milestone 3: Milestone 1 wants a thin path, not Protocol A.
4. **`run_session.py`** and enough of `launcher.py` to start it.
5. **Milestone 2**: `tools/check.py`, `tools/validate_session.py`, `tatp/screenshots.py`, and
   the literals test SPEC.md 4.2 asks for ("a test greps for violations"). Then finish the
   `check` target and delete its INCOMPLETE GATE line.
6. Run the **spec-review** agent before declaring Milestone 1 done
   ("Use the spec-review agent to review this diff against docs/SPEC.md").

## Watch out for

- The `PreToolUse` hook rejects `&&`, `||`, `;`, `|`, `$(`, backticks and newlines **even
  inside a quoted string** — including inside a `git commit -m` message, which is easy to trip
  over. Put throwaway code in a file under `tools/`, not in `python -c`, and not in `/tmp`: the
  hook also refuses absolute paths outside the repository, which includes the session
  scratchpad.
- `mkdir` is not on the allow list. `DataFileCollection` creates its own folder, which is the
  right place for it anyway.
- Directory permissions do not stop an append to an existing file. If you are testing the
  data-write failure path, chmod the *file*, not the folder.
