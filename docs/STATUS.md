# STATUS

**Last updated:** 20 October 2026, late (on the lab PC).
**Milestone:** 6 (pilotable), in progress. **Priority: testing the code in demo mode** (S,
20 Oct). The real valve garment is not built yet, so everything that needs it is parked.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). `pilot/ux-review` (S's 20 Oct demo test, N7.F16a–n) is merged
into `main` and deleted. **`pilot/ux-batch-2`** (S's second 20 Oct message, N7.F17a–e) is in
review: see "Where things stand". Neither is pushed. **`pilot/swedish-docs` is parked
on purpose** (S, 16 Oct): Swedish SOP and setup guide, reviewed and pushed, with `main` merged
in, but both SOPs (`SOP.md` too) predate the 15 Oct and 16 Oct screens, so they wait for the
next SOP update. `main` is pushed.

---

## Where things stand

**The build runs a whole session** against the mock garment or the prototype sleeve, and a
demonstration on either. `run_session.py` with no arguments opens **the hardware page**
(N7.F12e), then the launcher.

**Everything S raised on 15 Oct 2026 is in `main`**, every branch reviewed (`/code-review
high`, spec-review) with `make check` passing on the merged tree:
- **The pilot list** (N7.F10a–c, N7.F11a/b/c): notes saved and confirmed (they were never
  saved before); channel on/off in Check the hardware; a missing sound device refused, and
  any uncaught error stopping the session visibly and leaving it resumable; the experimenter
  screen calmer (two tiers of controls, one-line banners, the instruction fixed in place); each
  step saying what to do and what to say aloud, in the participant's language; introductions
  before each touch-calibration task; standby during waits; the session end and the
  intervention end announced.
- **The evening requests:**
  - the hardware page before the launcher, with live detection, alternatives to the remote
    for pilots and demos, and MacBook support (N7.F12e);
  - the warning cue is the text "Get ready" / "Gör dig redo" (N7.F12g);
  - a demonstration on a worn garment (fully manual) and a live garment display in the Demo
    controls (N7.F12f);
  - re-calibration at any time while touch is calibrated or delivered, with S's decision
    superseding R36's narrower recommendation (N7.F12a, N7.F10d).

**For S** (all in `docs/LOG.md` §7):
- **Decisions to confirm:**
  - the rekindle's touch restarts on the thermode-removal press (N7.F11b10);
  - re-calibration in the intervention: the For-S list in N7.F12a1 (sensitised skin, a
    Restart's "just uncomfortable", non-condition touch during the re-run, uneven across
    conditions, the self-start case, a crash mid-re-calibration);
  - a worn-garment demo is fully manual (N7.F12f1);
  - the mouse input draws the stop "!" on every screen, pilots and demos only (N7.F12e4);
  - the shortened interruption lines and the capsaicin-removal log label (N7.F11b12, b17).
- **Changed S-approved participant wording** (DRAFT): `screens.standby`,
  `audio_setup.find_level`, sv `choices.comparison.question` (N7.F11c6, c8, c11); the new
  `warning_cue` (N7.F12g1).
- **Open items still S's:** L11, L13, L3, L14, L15 (closes with lab check N2.10), L16 (now:
  whether a demo may name its condition, and whether a blinded experimenter may watch a demo's
  intervention with the garment display).

**The data files stay open for the session** (N7.F13a, merged 16 Oct). On the lab PC:
- `make check` passes on `main` (1354 tests, 36 validator checks in 193 s). It first failed at
  the validator's clean-up, because the simulated crash left its files open and Windows cannot
  delete an open file; the harness now closes them, as the OS does for a dead process.
- Reopening a file per row costs 0.146 ms there (0.004 ms kept open), a hundredth of the Mac's
  14 ms, so Defender does not by itself explain the lab PC's whole-demo stall.
- That stall is nonetheless gone: the whole-demo test passed in 10 of 10 parallel copies, twice
  (it failed in 1–2 of 10 before). Its cause on the lab PC is unexplained; if it returns, look
  there first (section 3, item 2, below).

**S's requests of 16 Oct are in `main`** (N7.F14a–e, merged 20 Oct; `/code-review high` and
spec-review done, one finding kept, see N7.F14c): the welcome says only that a touch comes
next, and a new `practice_intro` before the session's first practice carries the scale
explanation; touch calibration's estimation run waits a fixed 4.5 s window (1.5 s on a demo's
mock garment) so the pause cannot give a catch trial away; demo pinprick and brush rests
0.5 s; the experimenter sees the next pinprick or brush application with a countdown through
the interval; "Please wait" through any rest over 1 s. `make check` passes on `main` on the lab
PC (1360 tests, 36 validator checks, 224 screens), with the six changed or new participant
screens (`welcome`, `practice_intro`, `please_wait`, en and sv) approved there.

**S's demo test of 20 Oct is in `main`** (N7.F16a–n; `/code-review high` and spec-review done,
their findings fixed or answered in N7.F16n; `make check` passes on the lab PC: 1365 tests, 36
validator checks, 224 screens), in sessions and demonstrations alike:
- Next step is pressable only while a press does something, Space presses it, and every
  button shows its press; a three-condition test holds when it becomes pressable (blinding,
  **for S to confirm**, N7.F16d).
- Each filament and brush stroke: "Get ready" through the cue, then "Now: apply", then Next
  step says applied and the scale follows `rating_cue_delay_s` later (new column
  `stimulus_delivered_iso`; **for S to confirm**: the 9 s kept, from the press, N7.F16f).
- A timeline of the phases in the phase row; one channel display for sessions and demos.
- The demo controls along the foot of the experimenter window, each saying what it would do
  (Skip, Auto-run, Fast-forward, the clock, the remote's buttons lit).
- With the R400 plugged in a demo hears only it, also behind another program.
- Status line cleared between stages; "1 of 3" in the preference selection; the skin marked
  at the start of pre-sensitisation; "This rating is not recorded".
- 78 experimenter screens and 4 participant screens re-approved (listed in the commit).

**S's second message of 20 Oct, on `pilot/ux-batch-2`** (N7.F17a–e; `make check` passing;
`/code-review high` and spec-review next, then merge):
- **The scale comes at the delivery press**; the 13–17 s interval runs from that press and its
  countdown tells the experimenter when the next may be applied (N7.F17a). `rating_cue_delay_s`
  is gone.
- The zone diagram back to 200 px, the channel display beside it (N7.F17b); the simulated
  participant holds, settles and taps, judging only what it feels (N7.F17c); demo switches for
  who presses at any time, Auto-run, "Demo vs session…" (N7.F17d).
- The build's own walk-through list (N7.F17e): Next step never means "no" (own buttons for the
  other answer); only answers that will be taken are offered; abort pauses first and ends on the
  end screen; disconnect asks; the note's "saved at" goes; Enter in the re-run dialog; short
  re-calibration dialogs; Start always pressable; the hardware page's garment carried over; a
  hint for ▶ before the marker; Space/P/R; no-response warning; link lost in red in the alert
  row; "Resuming…"; the rehearsal's expected stop; which anchor; "Applied: …" after the press.
- `CLAUDE.md` "Engineering lessons" and `docs/UI_PRINCIPLES.md` §5.13–5.22 and §7, from the
  whole history (S's request); S does not review screens, the build re-approves them.

---

## Next steps

### 0. Finish `pilot/ux-batch-2`

Review (`/code-review high`, spec-review), fix, `make check`, merge `--no-ff`, `make check` on
`main`, delete the branch. Left from the walk-through, not yet done: long read-aloud scripts in
the four-line instruction; mapping's tick count and a warning when a path ends at the step
limit; Discard with no confirm; Next step drawn pressable in the screenshot samples where a
session would grey it.

### 1. Test the code in demo mode — the priority (S, 20 Oct; LOG N7.F15a)

```
conda run -n tatp-study-1 python run_session.py --demo --sim-participant watch --session 1 --experimenter SM --garment mock
```

On the lab PC or S's MacBook, with no hardware. A demo runs every stage and screen, and the
session plan, through the real code (N7.D23). It only finishes stages early, never skips
them. What it changes: rests 0.5 s (N7.F14b), the estimation window 1.5 s and its settle 0.5 s on the mock (N7.F14e, N7.F16g), Skip,
Auto-run, Fast-forward and a faster clock (mock only, N7.F16j), the example patterns, and every
keyboard counting as the remote unless the R400 is plugged in (N7.F16a). So it tests the flow,
the screens and the data, but not real stimuli or real timing. Record what turns up in LOG and
fix it on a `pilot/` branch.

1. **Walk a whole session as both people, in English and Swedish:** welcome, the new
   `practice_intro`, the introductions before each touch-calibration task, the read-aloud
   lines, standby, "Please wait", the intervention end and the session end.
2. **A note and its confirmation.**
3. **Re-calibration** in calibration and in the intervention: the flow only (N7.F12a).
4. **Skip calibration:** offered after 3 estimation ratings (`pilot_skip_min_ratings`);
   calibration ends with sensible fallbacks (N7.F8b).
5. **Touch calibration's estimation run:** "Get ready" and "Please wait" through the 1.5 s
   window, with nothing before a catch trial that sets it apart (N7.F14e).
6. **The interval countdown's wording** ("Next: … Deliver in N s", N7.F14c). With 0.5 s rests
   this checks the wording only. Whether it helps needs real intervals (section 2).
7. **Skip, Auto-run and Fast-forward** at each stage, and that each says what it would do.
8. **Since N7.F16:** Space for Next step; Next step greyed whenever nothing waits for it; the
   timeline; "Get ready" then "Now: apply" then Space for each filament and brush stroke; the
   R400 behind Notepad; the remote's buttons lighting in the demo panel; "1 of 3" in the
   preference selection; the skin-marking step.
9. **On S's MacBook:** the participant window stepping aside for a dialog (N7.F12e5). The
   rest of the MacBook hand check passed on 16 Oct.

### 2. Lab checks that need lab hardware but not the real sleeve (after section 1)

- **R400, in a non-demo session (`raw_input`):** hold acceleration (N7.F7b); tap-step size in
  the log (N2.9); remote routing to the participant window (N7.I1); **L15, the seven steps of
  lab check N2.10** (LOG §2).
- **The HP participant monitor at 1.5 scaling** (N7.U10(d)).
- **Sound:** the device on the hardware page; alerts not audible over the noise (L3, L13).
- **The interval countdown with real 13–17 s intervals:** does it help the experimenter
  (N7.F14c)?
- **The prototype sleeve:** Skip calibration on it, and a first feel of the estimation
  window and re-calibration. The real sleeve's ramps decide (section 5).
- **A rehearsal** with a stand-in participant, the R400 and the divider.
- The 16 Oct screens on the lab PC are covered by section 1.

### 3. Software, alongside

1. **Make `make check` pass on a Mac.** All of these failures predate N7.F14:
   - lint: conda-forge's osx `ruff` 0.17 has no Python module, so `python -m ruff` fails; the
     Makefile could call `ruff check .`;
   - two tests assume the lab platform without pinning it:
     `test_devices.py::test_the_lab_setup_changes_nothing` (`key_source`) and
     `test_hardware_check.py::test_a_device_that_cannot_play_at_the_configured_settings_says_why`
     (`stand_in`, which N7.F12e5 says is right off `lab_platform`);
   - six font-metric tests (`test_ui.py` interruption line 29 px > 28 px, `test_vas.py` ×4) and
     218 of 220 screenshots differ, because the references and metrics come from the lab PC;
   - the conda shell function is broken in the Claude app's shell on the MacBook, so
     `Makefile.local` points `make` at `/Users/sarmc72/miniconda3/bin/conda`.
2. **Left open from the review of N7.F13a:**
   - At the validator's 1000× clock the pattern timer is always due. On a slow enough machine
     it can still starve every other timer, including the validator's own 120 s guard. A
     wall-time floor on timer intervals, or a guard outside the Qt loop, would turn a hang into
     a failure.
   - A batch only partly written before a write error is retried whole, leaving a broken line
     (pre-existing, no row lost).
   - `tests/test_session_runner.py::test_the_session_ends_on_the_experimenters_last_next_step`
     failed once under parallel load on the Mac and passed 3 of 3 alone (a double press "at
     once" timed in real seconds). Watch for it.
3. **Left open, not blocking:**
   - preflight's sound check can freeze the launcher for up to 8 s (N7.F12e2);
   - the 640 px laptop-height target is exceeded in the pilot case (fine at 1280×800);
   - the emergency stop does not stop the white noise;
   - the hold-acceleration integral is duplicated (N7.F7b);
   - the screenshot tolerance hides glyph-sized changes;
   - `--approve-matching` keeps only the last pattern.

### 4. When the screens have settled

1. **Update `SOP.md` for the 15 and 16 Oct screens** (hardware page, re-calibration, intros,
   standby, read-aloud lines, about 45 quoted texts), then `SOP.sv.md` on
   `pilot/swedish-docs` to match.
2. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
3. **The adversarial review** (spec-review, §17.6) over the whole build before Milestone 6.

---

## 5. Parked until the real valve garment exists (S, 20 Oct)

- **Is the 4.5 s estimation window long enough** for the sleeve to deflate and reach the next
  pressure (N7.F14e)? The window must cover the slowest ramp, which is 4.22 s at the current
  rate limit (open item L2).
- **Do the estimation window and re-calibration pressures feel right** with real ramps?
- **Open items that wait on it:** 2 (pressure resolution), 3 (inflation rates), 5 (the real
  patterns), 8 (touch adjustment duration, mostly), 13 (channel overlap), 14 (valve-controller
  protocol), L2 (rate limit, deflation) and L11 (stop-rehearsal pressure). They still print at
  startup.
- **Hardware bring-up (§18.2):** `arduino_valves.py` (item 14) and `HARDWARE_BRINGUP.md`,
  starting from `tools/garment_bits.py` and N7.H2.
