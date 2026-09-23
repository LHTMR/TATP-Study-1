# STATUS

**Last updated:** 23 September 2026.
**Milestone:** 2 (the checks), in progress.
**Branch:** `main`.

---

## Where things stand

**Milestone 1, the vertical slice, is complete.** `run_session.py` opens both windows and runs
one anchor adjustment and one touch intensity rating. It then sets session t=0 and runs one
pinprick application inside intervention block 1 against the mock garment. It writes
`touchcal_adjust`, `touch_ratings`, `pinprick`, `garment`, `log` and `session`.

**Milestone 2 is missing one thing, the end-to-end validator.** `make check` runs the 351 unit
tests, the literals linter, the forbidden-terms test and the screenshot comparison. It passes
on the lab PC. It prints `INCOMPLETE GATE` because `tools/validate_session.py` does not exist.

**All 64 screens are approved and armed.** S approved them on 21 Sep 2026 and re-approved them
in the committed Roboto font on 23 Sep.

---

## Next steps

1. **Write `sim/responders.py`** (`SPEC.md` §17.5). Start with the normal responder, then add
   only those adversarial responders whose error path exists today. Candidates are:
   - confirming without moving the marker (`pressed_without_marker`);
   - pressing the emergency stop mid-trial;
   - holding the adjustment at maximum (the ceiling clamp).

   Check that each one really fires before keeping it.

2. **Write `tools/validate_session.py`** to the build rule in `SPEC.md` §17.3.

   Assert today:
   - the tables and their columns;
   - no required value missing;
   - condition and limb match `allocation.csv`;
   - monotonic timestamps;
   - provenance fields populated;
   - the calibrated force is a filament in `filaments.yaml`;
   - the same seed gives the same trial order;
   - the §16 blinding check.

   Declare as skips until their milestone lands:
   - row counts and block order (Milestone 5);
   - `out_of_range` (Milestone 3);
   - planned against actual offsets across a full grid (Milestone 5).

3. **Add a `validate` target to the `Makefile`, and delete its `INCOMPLETE GATE` line.**

4. **Close Milestone 2.** Run the spec-review agent, make `make check` pass, and commit.

---

## Later

In outline. Items marked *(specified)* already have their spec, schema, config and approved
wording, but no code.

- **Milestone 3, Protocol A in full.**
  - The long protocol's search, measurement and fixed-slope estimate.
  - The short protocol's jitter and site rotation, brush, and SH area mapping.
  - The intolerable cap *(specified; the flag is already written, nothing enforces it)*, and
    the experimenter's substitution control.
- **Milestone 4, Protocol B in full.**
  - The estimation run and fit *(specified)*, gain matching and pleasantness.
  - Equalisation *(specified)*. It is the intended caller of `_ChoiceScreen`, which nothing
    drives yet.
  - The fit preview *(specified)*.
  - `self_start_latency_ms` *(specified)*.
- **Milestone 5, the session.**
  - All twelve blocks, rekindle handling and resume.
  - The rest of the experimenter screen: zone diagram, hardware panel, countdown and controls.
    Each changes armed screens, so each needs S's re-approval.
  - Alerts, and the launcher of §4.1.
  - `audio.py`, which brings with it:
    - the masking check *(specified)*;
    - the emergency stop rehearsal *(specified)*;
    - moving `audio_setup.still_audible` into `choices` (`docs/LOG.md` N5.12).
  - The validator's skipped checks become live.
- **Milestone 6, pilotable.** `SOP.md` and `README`, screenshots frozen, adversarial review.
- **Hardware bring-up** (§18.2, a session with the real garment).
  - The real driver, once the serial protocol is agreed (open item 14).
  - `instruments.py`, and `HARDWARE_BRINGUP.md`.
