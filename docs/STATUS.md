# STATUS

**Last updated:** 16 October 2026 (on the lab PC).
**Milestone:** 6 (pilotable), in progress, in lab piloting.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). `pilot/keep-files-open` is merged and deleted locally; its copy
on `origin` is stale and can be deleted when `main` is pushed. **`pilot/swedish-docs` is parked
on purpose** (S, 16 Oct): Swedish SOP and setup guide, reviewed and pushed, with `main` merged
in, but both SOPs (`SOP.md` too) predate the 15 Oct screens, so they wait for the next SOP
update. `main` is ahead of `origin` and not pushed.

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

**The data files stay open for the session** (N7.F13a, merged 16 Oct). On the lab PC:
- `make check` passes on `main` (1354 tests, 36 validator checks in 193 s). It first failed at
  the validator's clean-up, because the simulated crash left its files open and Windows cannot
  delete an open file; the harness now closes them, as the OS does for a dead process.
- Reopening a file per row costs 0.146 ms there (0.004 ms kept open), a hundredth of the Mac's
  14 ms, so Defender does not by itself explain the lab PC's whole-demo stall.
- That stall is nonetheless gone: the whole-demo test passed in 10 of 10 parallel copies, twice
  (it failed in 1–2 of 10 before). Its cause on the lab PC is unexplained; if it returns, look
  there first (step 3 below).

---

## Next steps

1. **Make `make check` pass on a Mac** (all pre-existing, none caused by the change above):
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
2. **On S's MacBook, by hand** (only started so far: the automatic demo ran 90 s without an
   error; no one watched the windows). Check always-on-top and Spaces, CoreAudio at 48 kHz, the
   `tatp.devices` child process, fonts, key events. The conda shell function is broken in the
   Claude app's shell there; `Makefile.local` points `make` at
   `/Users/sarmc72/miniconda3/bin/conda`.
3. **Left open from the review of N7.F13a:** at the validator's 1000× clock the pattern timer is
   always due and can still starve every other timer, including the validator's own 120 s
   guard, on a slow enough machine; a floor on timer intervals in wall time, or a guard outside
   the Qt loop, would turn a hang into a failure. A batch only partly written before a write
   error is retried whole, leaving a broken line (pre-existing, no row lost).
4. **Re-run the lab session with the new screens**, starting at the hardware page: the sound
   device, a note and its confirmation, walk a session as both people (intros, read-aloud
   lines, the session end), try a re-calibration in calibration and in the intervention; and
   the 5 Oct checks still open (R400 hold acceleration N7.F7b, the touch-calibration pause R32,
   Skip calibration, the HP at 1.5, remote routing N7.I1, alerts over the noise, N2.9).
5. **L15: the lab check N2.10** (seven steps in LOG).
6. **Update `SOP.md` for the 15 Oct screens** (hardware page, re-calibration, intros, standby,
   read-aloud lines, about 45 quoted texts), then `SOP.sv.md` on `pilot/swedish-docs` to match,
   when S says the screens have settled.
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
