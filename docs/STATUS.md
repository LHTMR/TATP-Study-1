# STATUS

**Last updated:** 15 October 2026 (night).
**Milestone:** 6 (pilotable), in progress, in lab piloting.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). No branch of this session is open. `pilot/swedish-docs`
belongs to another session. `make check` needs the PC to itself: parallel test runs stall the
whole-demo test and the validator (an investigation of that stall is under way, below).
`main` is ahead of `origin` and not pushed.

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
- **Screens to review:** about 150 changed or added on 15 Oct (rows N7.F10b–N7.F12), plus the
  earlier list.
- **Open items still S's:** L11, L13, L3, L14, L15 (closes with lab check N2.10), L16 (now:
  whether a demo may name its condition, and whether a blinded experimenter may watch a demo's
  intervention with the garment display).

---

## Next steps

1. **On S's MacBook** (once `main` is pushed and pulled; nothing here is verified on a Mac):
   `conda env create -f environment.yml` (first time), `conda activate tatp-study-1`,
   `python run_session.py`. The page should show a window on this screen, the system default
   sound, the keyboard input (← → Return, full stop stops). Continue → Run a demo. From a
   terminal: `python run_session.py --demo --sim-participant watch`. Report anything that
   fails: always-on-top and Spaces, CoreAudio at 48 kHz, the `tatp.devices` child process,
   fonts, key events.
2. **The whole-demo test stall under load** (always at block.1, the first filament).
   Investigated 15 Oct: reproduced with 10 parallel copies (1–2 of 10 fail). The session state
   is consistent; one Qt timer (a pinprick trial's or the series' advance) is overdue and never
   delivered to the test's own `processEvents()` + `sleep` pump; a `QTest.qWait` at the stall
   delivers it and the session carries on. Real sessions run under `app.exec()` and are not
   known to be affected. Not fully explained. Proposed (test only, not yet applied or proven):
   replace the 300 s whole-run deadline with a stall detector that resets on log progress, and
   pump with `QTest.qWait(1)`; re-run the 10-copy check
   (`make test-one ARGS="tests/test_demo.py::test_a_whole_demonstration_runs_quarantined_and_recorded_as_one -n 10 --dist=each"`).
   The same pump idiom is in tests/test_protocol_a.py, test_protocol_b.py,
   test_session_runner.py and tests/virtual_participant.py.
3. **Re-run the lab session with the new screens**, starting at the hardware page: the sound
   device, a note and its confirmation, walk a session as both people (intros, read-aloud
   lines, the session end), try a re-calibration in calibration and in the intervention; and
   the 5 Oct checks still open (R400 hold acceleration N7.F7b, the touch-calibration pause R32,
   Skip calibration, the HP at 1.5, remote routing N7.I1, alerts over the noise, N2.9).
4. **L15: the lab check N2.10** (seven steps in LOG).
5. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
6. **The adversarial review** (spec-review, §17.6) over the whole build before Milestone 6.
7. **Left open, not blocking:** preflight's sound check can freeze the launcher up to 8 s
   (N7.F12e2); the 640 px laptop-height target is exceeded in the pilot case (fine at
   1280×800); the emergency stop does not stop the white noise; the hold-acceleration integral
   is duplicated (N7.F7b); the screenshot tolerance hides glyph-sized changes;
   `--approve-matching` keeps only the last pattern.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):** `arduino_valves.py` (open item 14);
  the rate limit (L2) and the inflation rates (item 3); `HARDWARE_BRINGUP.md`, starting from
  `tools/garment_bits.py` and N7.H2.
