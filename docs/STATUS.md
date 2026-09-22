# STATUS

**Last updated:** 13 October 2026.
**Milestone:** 2 (the checks), nearly done: three review findings and a lab-PC gate run remain.
Milestone 3 is next.
**Branch:** `main`.

---

## Where things stand

**Milestone 1, the vertical slice, is complete.** `run_session.py` opens both windows and runs
one anchor adjustment and one touch intensity rating. It then sets session t=0 and runs one
pinprick application inside intervention block 1 against the mock garment. It writes
`touchcal_adjust`, `touch_ratings`, `pinprick`, `garment`, `log` and `session`.

**Milestone 2 is built except for what step 1 below lists.** `sim/responders.py` has the normal
responder and six of the nine adversarial ones; the other three are named in `sim.DEFERRED` with
the milestone that gives each an error path. **The six are press plans, not yet checks:**
nothing runs them through a session, so none asserts its error path end to end (step 1). `tools/validate_session.py` runs the slice twice headless with one seed and
checks the files (`docs/LOG.md` N6.33); `make check` runs it and names every failed stage. Its
first runs found lost adjustment taps, now fixed (N6.32).

**Gate, as last run (Mac, 13 Oct 2026):** 412 tests pass, lint clean, validator 14 passed and
7 declared skips. Screenshots: 60 of 64 differ from the references by 0.6–5 % — sub-pixel
glyph rasterisation, macOS against the Windows-approved Roboto references; same font, layout
and wording. The gate only needs to pass on the lab PC, where the references were approved,
and it has not yet been run there with the validator in it. On the lab PC, check that
`make shots` passes. Don't re-approve the references from the Mac.

This work was built on the Mac before the lab PC's font and docs changes, and merged onto them
on 13 Oct 2026; the Mac branch is kept as `mac-backup` until the lab run passes.

**All 64 screens are approved and armed**, in the committed Roboto font (S, 23 Sep 2026).

---

## Next steps

1. **Close the three Milestone 2 findings from the 13 Oct 2026 spec review.**
   - **The adversarial responders assert nothing yet** (`SPEC.md` §17.5). `validate_session.run`
     takes `participant_cls` but nothing passes one. Run each built responder through the slice
     and check its path fires in the data: the intolerable flag and `intolerable_rating` event
     (`RatesMaximum`), the `pressed_without_marker` log row (`ConfirmsWithoutMoving`), the stop
     with no `pinprick` row (`StopsMidRating`), the configured ceiling (`HoldsToMaximum`). The
     docstrings in `sim/responders.py` already claim these.
   - **`sim/responders.py` copies the observer model** where §17.3's build rule says it imports
     it from `docs/calibration_sim.py`. A test catches drift, but the code contradicts the spec:
     import it, or amend §17.3 and log why.
   - **`blinding_text` has no test showing it can fail.** Plant a forbidden term in a
     participant file and a condition label in an experimenter file and watch it fail.

2. **On the lab PC, pull and run `make check`.** If it passes with step 1 done, Milestone 2 is
   closed; delete the `mac-backup` branch on the Mac.

3. **Before Milestone 3, settle `docs/LOG.md` N6.35** — which generator `Session.rng` should be.
   Milestone 3 is the first code to draw from it, and switching after sessions are recorded
   invalidates their seed reproduction.

4. **Milestone 3, Protocol A in full** (`SPEC.md` §18, §8). Read
   `docs/calibration_methods_comparison.md` first. As it lands, move these out of the
   validator's `DEFERRED` into real checks, each with a test in
   `tests/test_validate_session.py` that breaks the data and watches the check fail:
   - `out_of_range_set_correctly`, `calibrated_f40_is_a_filament`,
     `seed_reproduces_trial_order`;
   - the `calibration_pinprick`, `brush`, `mapping` and `sh_area` tables, from
     `NOT_YET_PRODUCED` to `PRODUCED` (`tables_present` fails until they move);
   - the two out-of-range responders in `sim.DEFERRED`.

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
  - The validator's remaining skips become live, and `stops_responding` gets its consumer.
- **Milestone 6, pilotable.** `SOP.md` and `README`, screenshots frozen, adversarial review.
- **Hardware bring-up** (§18.2, a session with the real garment).
  - The real driver, once the serial protocol is agreed (open item 14).
  - `instruments.py`, and `HARDWARE_BRINGUP.md`.
