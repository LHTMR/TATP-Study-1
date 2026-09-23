# STATUS

**Last updated:** 24 September 2026.
**Milestone:** 5 (the session), next. Milestones 2, 3 and 4 are merged. Acceleration push under
way (`CLAUDE.md`).
**Branch:** `accel/integration`.

---

## Where things stand

**The protocols exist, but only the Milestone 1 slice runs them.** `run_session.py` still runs
`SliceRunner`: one adjustment, one touch rating, one pinprick application. Everything else is
built and unit-tested as `Procedure`s (`tatp/procedure.py`), waiting for the Milestone 5
sequencer to call them.

- **Milestone 2:** `tools/validate_session.py` and `sim/`. `make check` is the full gate: 617
  tests, ruff, the validator (19 passed, 6 skipped) and 86 screens. It takes about 1–2 minutes.
- **Milestone 3, Protocol A:** `LongProtocol`, `ShortProtocol` and `BrushProtocol` in
  `tatp/pinprick.py`; `AreaMapping` and `MappingLedger` in `tatp/mapping.py`.
- **Milestone 4, Protocol B:** `TouchCalibration` → `TouchCalibrationResult.for_condition()`,
  and `DeliveryStart` in `tatp/touchcal.py`. `tatp/audio.py`, plus `MaskingCheck` and
  `StopRehearsal` in `tatp/setup_checks.py`.
- **Shared interfaces:** `tatp/interruption.py` owns the stop, the pause and the resume. The
  experimenter's actions are signals on `ExperimenterWindow`, with no buttons yet.

**For S to review, in `docs/LOG.md` §7:**
- the decisions taken during the push. The low-confidence ones are N7.C2 (the stage-1 gate
  numbers) and N7.B2 (the prior offsets, open item LB1);
- one drafted wording, N7.C1;
- 22 newly approved screens, N7.C24.

The stop-rehearsal screen shows `PLACEHOLDER` in its button until L12 is answered.

---

## Next steps

**Milestone 5, in two streams cut from `accel/integration`:**

1. **The session sequencer**, `tatp/session_runner.py`, replacing `SliceRunner`. It covers:
   - **Setup:** the masking check, then the stop rehearsal.
   - **Touch calibration.**
   - **Pre-sensitisation:** the long protocol, the short primary protocol and brush.
   - **Sensitisation and capsaicin:** timed and prompted only.
   - **Post-sensitisation:** the same measures, plus mapping.
   - **The intervention:** twelve blocks, launched by the experimenter, with the garment
     delivering `for_condition(session.condition)` and a rekindle that switches the garment off
     and on.
   - **Post-intervention.**

   Also in this stream:
   - one `IntolerableCap` per time point, and the F₄₀ prior carried forward (`prior_for`);
   - the noise stopped around mapping, and the pacing cue made audible;
   - due and overdue alerts;
   - the outstanding-distances prompt at close;
   - **resume (SPEC.md §15)** from the data files, including `touchcal_channels`;
   - the validator's full-grid checks becoming live.
2. **The experimenter screen and the launcher:**
   - buttons for every `ExperimenterWindow` signal;
   - the zone diagram, the hardware panel, the countdown and the fit preview;
   - the launcher of §4.1.

   These change the armed experimenter screens, so every one needs S's re-approval.

Review each stream (`/code-review high`, then spec-review) before it merges, and run `make check`
on the integration branch after.

---

## Later

- **Milestone 6:** `SOP.md` and `README`, screenshots frozen, the final adversarial review.
- **Hardware bring-up (§18.2):**
  - the real driver (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `instruments.py` and `HARDWARE_BRINGUP.md`.
