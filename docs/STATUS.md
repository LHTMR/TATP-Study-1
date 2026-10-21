# STATUS

**Last updated:** 21 October 2026 (on S's MacBook).
**Milestone:** 6 (pilotable), in progress. **Priority: testing the code in demo mode** (S,
20 Oct). The real valve garment is not built yet, so everything that needs it is parked.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). **`pilot/demo-feedback-2`** (N7.F18a–m, S's MacBook demo of
21 Oct) is committed, not merged, not pushed; see below. **`pilot/swedish-docs` is parked on
purpose** (S, 16 Oct): the Swedish SOP waits for the next SOP update. `main` is pushed.

---

## Where things stand

**The build runs a whole session** against the mock garment or the prototype sleeve, and a
demonstration on either. `run_session.py` with no arguments opens the hardware page (N7.F12e),
then the launcher. Everything S raised from 15 to 20 Oct (N7.F10–N7.F17) is in `main`, every
branch reviewed with `make check` passing on the lab PC; the history is in the git log and
`docs/LOG.md` §7.

**`pilot/demo-feedback-2`: S's demo of 21 Oct** (LOG N7.F18a–m):
- Experimenter keys work whichever window is active (a); **Jump to** replaces Skip and
  Fast-forward, back or forward, every stage, who presses untouched (b); Manual / Auto labels,
  "Next", "Finish session" (c).
- One panel headed Now / Prepare / Wait, waits counting down; a row of the phase's steps (d).
- The zone diagram beside the instruction shows the sites, mirrored for a left limb; x/N
  progress; the next filament cued while the participant rates; the substitution a drop-down
  with its own message (e). The distances box in the window, a column per time point (f). The
  garment grouped on the right (g). Due soon / due now / behind schedule (h). One Re-calibrate
  dialog (i). Noise only while the garment may run; the tick a click (j). The intervention's
  rest screen (k). The finish page on checking and uploading the data (l). Demo-data findings (m).
- **State on the Mac:** `make check` fails only on the 9 known Mac failures (section 3, item 1);
  1390 unit tests pass, validator 36/36, ruff and the literal lint clean.
- **Still to do on this branch:** `/code-review high`, then spec-review, fixes, then on the lab
  PC: `make check`, and re-approve the changed screens after looking at each against
  `docs/UI_PRINCIPLES.md` (the references are lab-PC renders, so the Mac cannot approve them):
  `make shots ARGS="--approve-matching 'experimenter_*'"`, then the participant
  `*_standby_intervention`. 18 screens are new. Then merge.
- **On the lab laptop:** the demo window with the open-items line is over 800 px tall (it was
  before this branch too); the session window is 583 px, 628 with a banner.

**For S** (all in `docs/LOG.md` §7):
- **Decisions to confirm:** the noise silent outside the garment's phases, so the cue sounds
  over silence there at the same level (N7.F18j); a demo's Jump-to fallbacks (N7.F18b); where
  each numbered site is drawn, a placeholder (open item 11, N7.F18e); the rekindle's touch
  restart (N7.F11b10); re-calibration in the intervention (N7.F12a1); a worn-garment demo
  fully manual (N7.F12f1); the mouse's "!" (N7.F12e4); shortened interruption lines (N7.F11b12,
  b17); Next step's pressable timing (N7.F16d); the scale at the delivery press (N7.F17a).
- **New and changed wording (DRAFT):** `screens.standby_intervention` (N7.F18k); the
  experimenter's headings, distances box, Re-calibrate dialog and finish page (N7.F18d, f, i, l).
- **Anatomy:** the placeholder figure is a right hand (its old comment said left); it is
  mirrored for a left limb.
- **Open items still S's:** L11, L13, L3, L14, L15, L16.

---

## Next steps

### 1. Test the code in demo mode — the priority (S, 20 Oct; LOG N7.F15a)

```
conda run -n tatp-study-1 python run_session.py --demo --sim-participant watch --session 1 --experimenter SM --garment mock
```

A demo writes its data to `data_demo/<time>/`. Record what turns up in LOG and fix it on a
`pilot/` branch.

1. **Walk a whole session as both people, in English and Swedish.**
2. **Since N7.F18:** Space, P and R with the participant window active (lab check: the R400
   and a plain keyboard on the lab PC, which the Mac could not test); Jump to forward and back
   at each phase, and the rows a back jump repeats; the headings and countdowns; the diagram's
   sites on a left and a right limb; the distances box across the three time points; the
   noise switching on and off only around the garment; the click; the finish page.
3. **Re-calibration** in calibration and in the intervention: both choices.
4. **Skip calibration** after 3 estimation ratings (N7.F8b).
5. **On S's MacBook:** the participant window stepping aside for a dialog (N7.F12e5).

### 2. Lab checks that need lab hardware but not the real sleeve

- **R400, in a non-demo session (`raw_input`):** hold acceleration (N7.F7b); tap-step size
  (N2.9); remote routing (N7.I1); **L15, lab check N2.10**.
- **The HP participant monitor at 1.5 scaling** (N7.U10(d)).
- **Sound:** the device on the hardware page; alerts over the noise (L3, L13); the click's
  loudness against the alert's (N7.F18j).
- **The interval countdown with real 13–17 s intervals** (N7.F18d).
- **The prototype sleeve:** Skip calibration, the estimation window, re-calibration.
- **A rehearsal** with a stand-in participant, the R400 and the divider.

### 3. Software, alongside

1. **Make `make check` pass on a Mac.** The 9 known failures, all predating N7.F18:
   - lint: `python -m ruff` fails with conda-forge's osx `ruff`; the Makefile could call
     `ruff check .`;
   - two tests assume the lab platform without pinning it: `test_devices.py::test_the_lab_setup_changes_nothing`,
     `test_hardware_check.py::test_a_device_that_cannot_play_at_the_configured_settings_says_why`;
   - `test_pinprick.py::test_a_slow_write_before_the_stimulus_due_does_not_delay_the_prompt`;
   - six font-metric tests (`test_ui.py` interruption line ×2, `test_vas.py` ×4), and the
     screenshots, because references and metrics come from the lab PC;
   - `Makefile.local` points `make` at `/Users/sarmc72/miniconda3/bin/conda`.
2. **Left open from earlier reviews:**
   - at the validator's 1000× clock the pattern timer can starve other timers on a slow machine;
   - a batch only partly written before a write error is retried whole (no row lost);
   - `test_session_runner.py::test_the_session_ends_on_the_experimenters_last_next_step` and
     `test_next_step_while_the_touch_comes_back_launches_nothing[participant_preferred]` each
     failed once under load and passed alone. Watch for them.
3. **Not blocking:** preflight's sound check can freeze the launcher up to 8 s (N7.F12e2); the
   emergency stop does not stop the white noise; the hold-acceleration integral is duplicated
   (N7.F7b); the screenshot tolerance hides glyph-sized changes; `--approve-matching` keeps
   only the last pattern.

### 4. When the screens have settled

1. **Update `SOP.md`** for the screens since 15 Oct (including N7.F18's Jump to, headings,
   distances box and finish page), then `SOP.sv.md` on `pilot/swedish-docs`.
2. **Freeze the screenshots** (`make shots ARGS="--freeze"`).
3. **The adversarial review** (spec-review, §17.6) over the whole build before Milestone 6.

---

## 5. Parked until the real valve garment exists (S, 20 Oct)

- **Is the 4.5 s estimation window long enough** for the slowest ramp, 4.22 s at the current
  rate limit (N7.F14e, L2)? Do the window and re-calibration pressures feel right?
- **Open items that wait on it:** 2, 3, 5, 8, 13, 14, L2, L11. They print at startup.
- **Hardware bring-up (§18.2):** `arduino_valves.py` (item 14) and `HARDWARE_BRINGUP.md`,
  starting from `tools/garment_bits.py` and N7.H2.
