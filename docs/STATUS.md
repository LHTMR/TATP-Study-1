# STATUS

**Last updated:** 15 October 2026 (evening).
**Milestone:** 6 (pilotable), in progress, in lab piloting.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). **Open:** `pilot/recalibration-after-stop`, the last item of
S's 15 Oct pilot list (below), being implemented. `pilot/swedish-docs` belongs to another
session. `make check` needs the PC to itself: parallel test runs stall the whole-demo test
and the validator.

---

## Where things stand

**The build runs a whole session**, against the mock garment or the prototype sleeve, and a
demonstration mode (launcher *Run a demo*, LOG N7.D23). `run_session.py` with no arguments
opens the launcher (§4.1).

**S's pilot list of 15 Oct 2026 is done in `main`, except re-calibration after a stop**
(in progress). Every branch below had `/code-review high` and spec-review, and `make check`
passed on the merged tree (1215 tests, 36 validator checks, 202 screens):
- **Notes were never saved** (N7.F10a): the field was connected to nothing since Milestone 5.
  Now logged (`experimenter_note`) and confirmed in the field. Sessions before 15 Oct have none.
- **Check the hardware's channel buttons say on/off** (N7.F10b).
- **The demo stuck in Förberedelse** (N7.F10c): the masking check's noise could not open the
  sound device (inferred from the log, likely the Bose headset not connected). Preflight now
  refuses a sound device that cannot be opened; an uncaught error now stops the session
  visibly and leaves it open to a resume.
- **The screen review** ("mycket för ögonen"; "not always clear what was going on"), three
  streams, rows N7.F11a/b/c:
  - experimenter layout: two tiers of controls, idle ones hidden; one-line banners; the
    instruction fixed in place and dimmed during a stop; the substitution field only during
    a filament trial (it used to lose what was typed);
  - experimenter instructions: what to do and say at each step, read-aloud sentences in the
    participant's language (`say:`), per-stage ready lines, heat/capsaicin/rekindle steps
    including a thermode-removal Next step, warnings that persist;
  - participant flow: an intro before each touch-calibration task, the cue explained,
    standby during waits and decisions, a break between ratings, a session end that stays up
    and an intervention end that waits.
- **Re-calibration after a stop** (N7.F10d, [R36](research/R36-recalibration-after-emergency-stop.md)):
  offered in touch calibration only (Rebalance channels / Restart calibration, once per
  session); Resume only elsewhere, including the intervention.

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Changed S-approved participant wording** (DRAFT): `screens.welcome` (the circle
  "marks the start of each step"), `screens.standby`, `audio_setup.find_level`, sv
  `choices.comparison.question` (N7.F11c2, c6, c8, c11).
- **Decisions to confirm:**
  - the rekindle's touch restarts on the thermode-removal press, not automatically (N7.F11b10);
  - the shortened interruption lines (N7.F11b12) and the capsaicin-removal log label (b17);
  - no re-calibration during the intervention; lowering a channel or continuing with the
    touch off is S's (N7.F10d);
  - the intro screens add about a minute to touch calibration (N7.F11c1).
- **Screens to review:** about 90 experimenter and 40 participant screens changed or added
  today (N7.F10b, N7.F11a9, b21, c1–c11), plus the earlier list (N7.F3–F9, U-rows).
- **Drafted wording:** every N7.F10 and N7.F11 row; earlier N7.F3, F4, F6–F8, T1, T2, U-rows.
- **Open items still S's:** L11 rehearsal pressure, L13 noise ceiling and cue, L3 alert
  metering, L14 a lost sleeve link, L15 (fixed, closes with lab check N2.10), L16 demo
  conditions.

---

## Next steps

1. **Finish `pilot/recalibration-after-stop`**: review (code-review high, spec-review),
   `make check`, merge.
2. **Re-run the lab session with the new screens**, starting with Check the hardware:
   - the sound device: `audio.participant_device` is the Bose Bluetooth headset; preflight
     now refuses a session without it. Use the device the study will use, and restart the
     program after switching headphones on;
   - type a note and check the confirmation; check the log has it;
   - walk a session as both people: do the intros, the read-aloud lines and the session end
     read right; is the calmer experimenter screen easier the first time;
   - the 5 Oct checks still open: the R400 hold acceleration (N7.F7b), the touch-calibration
     pause (R32), Skip calibration, the participant screen on the HP at 1.5, the remote
     routing (N7.I1), alerts audible over the noise, taps never lost (N2.9).
3. **L15: the lab check N2.10** with the R400 and the laptop keyboard (seven steps in LOG).
4. **Watch a demonstration on a display** and decide L16.
5. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
6. **Run the adversarial review** (spec-review, §17.6) over the whole build before declaring
   Milestone 6 done.
7. **Left open, not blocking:**
   - a demonstration's simulated experimenter can resume the mock garment under the error
     dialog (N7.F10c);
   - the 640 px laptop-height target is exceeded by the pilot case (banner plus open items,
     about 657 px); fine at 1280×800 (N7.F11a);
   - the mock's injected faults never lose the link (N7.U8 (2)); the emergency stop does not
     stop the white noise;
   - the hold-acceleration integral is duplicated (N7.F7b);
   - the screenshot tolerance (0.2 %) hides glyph-sized changes;
   - `--approve-matching` keeps only the last pattern given.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):**
  - `arduino_valves.py` (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`, starting from `tools/garment_bits.py` and N7.H2.
