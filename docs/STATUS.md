# STATUS

**Last updated:** 16 October 2026 (early morning, on S's MacBook).
**Milestone:** 6 (pilotable), in progress, in lab piloting.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). **`pilot/keep-files-open` is open, reviewed (`/code-review
high`, spec-review, fixes applied) and not merged**: `make check` cannot pass on the Mac for
reasons unrelated to it (below), so it waits for `make check` on the lab PC. `pilot/swedish-docs`
belongs to another session. `main` is ahead of `origin` and not pushed.

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

1. **Merge `pilot/keep-files-open` from the lab PC** (N7.F13a): pull, `make check`; if it
   passes, merge `--no-ff` into `main`, `make check` on `main`, delete the branch. It keeps the
   data files open (unbuffered) instead of reopening them per row, which Microsoft Defender
   made cost 14 ms a row on S's MacBook. That cost was the cause of the stalls: on the Mac it
   took `make check` from 1 h 42 min with five stalled tests and a hung validator to a 3½-min
   suite and a 206 s validator with no stalls. **Very probably the same as the lab PC's
   whole-demo stall under parallel load** (formerly step 2 here; not checked on the lab PC).
   Re-run the 10-copy check there after the merge
   (`make test-one ARGS="tests/test_demo.py::test_a_whole_demonstration_runs_quarantined_and_recorded_as_one -n 10 --dist=each"`).
2. **Make `make check` pass on a Mac** (all pre-existing, none caused by the change above):
   - lint: conda-forge's osx `ruff` 0.17 has no Python module, so `python -m ruff` fails; the
     Makefile could call `ruff check .`;
   - two tests assume the lab platform without pinning it:
     `test_devices.py::test_the_lab_setup_changes_nothing` (`key_source`) and
     `test_hardware_check.py::test_a_device_that_cannot_play_at_the_configured_settings_says_why`
     (`stand_in`, which N7.F12e5 says is right off `lab_platform`);
   - six font-metric tests (`test_ui.py` interruption line 29 px > 28 px, `test_vas.py` ×4) and
     218 of 220 screenshots differ, because the references and metrics come from the lab PC.
   - The STATUS demo command lacked `--session` and `--experimenter`; it is
     `python run_session.py --demo --sim-participant watch --session 1 --experimenter SM --garment mock`.
3. **On S's MacBook, by hand** (only started so far: the automatic demo ran 90 s without an
   error; no one watched the windows). Check always-on-top and Spaces, CoreAudio at 48 kHz, the
   `tatp.devices` child process, fonts, key events. The conda shell function is broken in the
   Claude app's shell there; `Makefile.local` points `make` at
   `/Users/sarmc72/miniconda3/bin/conda`.
4. **Left open from the review of N7.F13a:** at the validator's 1000× clock the pattern timer is
   always due and can still starve every other timer, including the validator's own 120 s
   guard, on a slow enough machine; a floor on timer intervals in wall time, or a guard outside
   the Qt loop, would turn a hang into a failure. A batch only partly written before a write
   error is retried whole, leaving a broken line (pre-existing, no row lost).
5. **Re-run the lab session with the new screens**, starting at the hardware page: the sound
   device, a note and its confirmation, walk a session as both people (intros, read-aloud
   lines, the session end), try a re-calibration in calibration and in the intervention; and
   the 5 Oct checks still open (R400 hold acceleration N7.F7b, the touch-calibration pause R32,
   Skip calibration, the HP at 1.5, remote routing N7.I1, alerts over the noise, N2.9).
6. **L15: the lab check N2.10** (seven steps in LOG).
7. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
8. **The adversarial review** (spec-review, §17.6) over the whole build before Milestone 6.
9. **Left open, not blocking:** preflight's sound check can freeze the launcher up to 8 s
   (N7.F12e2); the 640 px laptop-height target is exceeded in the pilot case (fine at
   1280×800); the emergency stop does not stop the white noise; the hold-acceleration integral
   is duplicated (N7.F7b); the screenshot tolerance hides glyph-sized changes;
   `--approve-matching` keeps only the last pattern.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):** `arduino_valves.py` (open item 14);
  the rate limit (L2) and the inflation rates (item 3); `HARDWARE_BRINGUP.md`, starting from
  `tools/garment_bits.py` and N7.H2.
