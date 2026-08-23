# PROGRESS

Handover file (CLAUDE.md). Between `docs/SPEC.md`, this file and the git log, a fresh session
should need nothing from any previous conversation.

**Last updated:** 23 August 2026, end of session 1.
**Milestone:** 1 (the vertical slice) — *in progress, not complete.*

---

## Read this first

**No code in this repository has been executed yet.** The conda environment is verified; the
Python is not. Session 1 ended before anything could be run, so every module below is written
but unproven. The first thing the next session should do is run the verification below and fix
whatever falls out — do not assume any of it works.

```
conda run -n tatp-study-1 python tools/make_allocation.py     # config/allocation.csv does not exist yet
conda run -n tatp-study-1 python -m pytest                     # no tests exist yet either
```

`config/allocation.csv` is **missing**, and `tatp/config.py` asserts that the file named by
`design.allocation_file` exists — so **config loading currently fails by design** until
`tools/make_allocation.py` has been run once. That is the intended fail-fast behaviour
(SPEC.md 6), not a bug, but it means nothing else can be smoke-tested until it is generated.

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

---

## What exists

| File | State |
|---|---|
| `docs/DATA_SCHEMA.md` | **Complete.** All 11 tables of SPEC.md 14.2, with the session-key list. Written to be *machine-parsed* — see below |
| `config/study1.yaml` | Design parameters. Covers protocols A and B, mapping, patterns, cues |
| `config/hardware.yaml` | Garment limits, adjustment curve, R400 keys, screens, audio, data folder |
| `config/schedule.yaml` | `generate:` / `overrides:` / `validation:` per SPEC.md 7.1 |
| `config/filaments.yaml` | All 11 Aesthesio filaments, 19.6–2940 mN. Every `force_measured_mn` is null |
| `config/open_items.yaml` | The SPEC.md 20 warning mechanism, plus four locally-raised items — see below |
| `config/text/*.yaml` | All four. VAS wordings from SPEC.md 10.6 verbatim; screens are placeholders |
| `config/patterns/examples/static_sham.*` | Added — the sham condition needed a pattern to point at |
| `tatp/config.py` | Load, validate against `SCHEMA`, cross-check language key sets, open-item resolution |
| `tatp/allocation.py` | Read and validate the counterbalancing file |
| `tatp/clock.py` | `perf_counter` session clock with the accelerated mode SPEC.md 17.3 needs |
| `tatp/provenance.py` | git SHA, versions, package list, cloud-sync detection |
| `tools/make_allocation.py` | Counterbalance generator. **Not yet run** |
| `pyproject.toml` | ruff (line length 96) and pytest config |

## What does not exist yet

`tatp/session.py`, `schedule.py`, `datafiles.py`, `responder.py`, `audio.py`, `screenshots.py`,
all of `tatp/ui/`, all of `tatp/garment/`, `pinprick.py`, `touchcal.py`, `instruments.py`,
`launcher.py`, `run_session.py`, `tools/` (except `make_allocation.py`), `sim/`, `tests/`,
`Makefile`, `README`, `SOP.md`, `HARDWARE_BRINGUP.md`, `config/allocation.csv`.

`make check` **does not exist**, so the gate has never run.

---

## Decisions taken this session, not already in SPEC.md

1. **`docs/DATA_SCHEMA.md` is parsed, not just read.** It declares a parsing contract: a
   `### table_name` heading followed by a table with the header
   `| Column | Type | Unit | Required | Description |`. `tatp/datafiles.py` and
   `tools/validate_session.py` both read it, so the writer and the validator cannot drift from
   the documentation. Edit the markdown and both follow. **This is the reason not to
   reformat those tables casually.**

2. **`config/open_items.yaml` is the SPEC.md 20 mechanism.** Each item names a dotted config
   path in `resolved_when:`; the loader warns for every path that is still null. This makes
   "warns at startup for each unresolved one" automatic rather than something a future session
   has to remember. Adding an open item means adding a row there, not code.

3. **Four locally-raised open items (`L1`–`L4`)**, for values the spec *requires to exist* but
   does not fix. They are flagged exactly like the numbered ones rather than quietly defaulted:
   - **L1** software pressure ceiling — SPEC.md 13 requires one below the 250 kPa hardware
     maximum but gives no number. **200 kPa is a working value, not an agreed limit.**
   - **L2** pressure rate limit — 60 kPa/s, chosen to sit just above the 50 kPa/s top
     adjustment rate of SPEC.md 10.3.
   - **L3** audio levels in dBFS — placeholders; set with a meter at the headphones.
   - **L4** participant instruction/standby/training screen text — see below.

4. **Participant screen text is a placeholder, deliberately.** SPEC.md 10.6 supplies the VAS
   questions and anchors and nothing else. The welcome, standby, session-end, adjustment,
   comparison, preference and mapping screens are not in any source document and are bound by
   Bilaga 1 and the participant-facing ethics attachments (SPEC.md 1.3, 20 item 12). Inventing
   them would be exactly the substitution CLAUDE.md forbids, so every one is a string beginning
   `PLACEHOLDER`, `Config.has_placeholder_text()` detects them, and the experimenter screen is
   to carry an unmissable banner while any remain. **This is the main thing S needs to supply.**
   The English proportionality-training wording is also absent — SPEC.md 10.6 gives Swedish only.

5. **Experimenter Swedish was written from scratch** (`experimenter_sv.yaml`). It is not
   ethics-bound and not participant-facing, so it did not need to be sourced. Worth a read.

6. **Allocation design.** Condition order is drawn from a pool holding each of the 6
   permutations equally often, so orders are balanced to within one participant. Starting limb
   alternates by participant *index* rather than randomly — with 41 participants that balances
   21/20 exactly, where random assignment would not. Codes are `01`–`41`. Default seed
   `20260823`, recorded in a `#` header line inside the CSV.

7. **`static_sham` pattern added** with all five channels held on, so the sham matches the
   moving patterns in spatial extent and differs only in motion. A single-channel sham would
   differ in extent too. **Assumption — confirm at bring-up.**

8. **Permissions and `CLAUDE.md` tightened** (see the git log). Denied the bypass class —
   `find`, `sed`, `awk`, `perl`, `tee`, `xargs`, `cp`, `ln`, `dd`, and the shell wrappers
   `bash -c` / `sh` / `zsh` / `env` / `eval` / `exec` / `nohup` / `time` / `watch` — because
   each is a way to run something the deny list would otherwise have caught (`find -delete`
   deletes without invoking `rm`). Also denied `git checkout` / `git restore` / `git config`;
   use `git switch`. Allowed `grep`, `rg`, `git ls-files`, `git ls-tree`, `git rev-parse`,
   `conda search`.
   **Known remaining hole, stated rather than papered over:** `conda run … python` can execute
   anything and the Makefile needs it. It is narrowed to the four forms the Makefile uses
   rather than allowed wholesale.

---

## Next steps, in order

1. **Run `tools/make_allocation.py`** and commit `config/allocation.csv`. Nothing else can be
   smoke-tested until it exists. This closes SPEC.md 20 item 10.
2. **Smoke-test `tatp/config.py`** — `load("sv", "en")` — and fix what breaks. It has never
   been imported. Check especially `resolve()` against the `[*]` paths, and
   `_load_open_items()`, which mutates `loaded` while iterating.
3. **`tatp/datafiles.py`** — parse `DATA_SCHEMA.md`, then open-append-close per row
   (SPEC.md 14.3). This is the one place a narrow `try`/`except` is permitted, and only to
   avoid losing an already-collected trial.
4. **`tatp/garment/{base,mock}.py`** — the mock is a first-class deliverable, not scaffolding
   (SPEC.md 12.1).
5. **Finish the Milestone 1 slice**: minimal `session.py`, a VAS widget, a three-application
   calibration, one pinprick trial, one touch rating, producing real data files with full
   provenance. Keep the long protocol's search/bracket/cap logic for Milestone 3 — Milestone 1
   wants a thin path, not Protocol A.
6. **Milestone 2**: `Makefile`, `tools/check.py`, first tests, validator, screenshot mode.
7. Run the **spec-review** agent before committing Milestone 1
   ("Use the spec-review agent to review this diff against docs/SPEC.md").

## Watch out for

- The `PreToolUse` hook rejects `&&`, `||`, `;`, `|`, `$(`, backticks and newlines **even
  inside a quoted string**, so `python -c "a=1; b=2"` is refused. Put throwaway code in a file
  under `tools/`, not in `-c`, and not in `/tmp` — the hook also refuses absolute paths outside
  the repository, which includes the session scratchpad.
- Every file written in session 1 initially picked up a stray trailing `</content>` line from a
  tooling slip; all 20 were stripped, but if something fails to parse, check the last line
  first.
