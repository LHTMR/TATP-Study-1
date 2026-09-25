# STATUS

**Last updated:** 25 September 2026.
**Milestone:** 6 (pilotable), in progress. Milestones 2–5 and the Milestone 6 work so far,
including the UI review, are in `main` (merged at S's request, 25 Sep 2026). Acceleration
push under way (`CLAUDE.md`).
**Branch:** `accel/integration`, level with `main`. The UI review had both pre-merge reviews at
every step, with their findings fixed (N7.U5, N7.U6, N7.U8).

---

## Where things stand

**The build runs a whole session**, against the mock garment or the prototype sleeve. The garment
is chosen at launch. `run_session.py` with no arguments opens the launcher (§4.1).

**The UI review branch (`docs/LOG.md` N7.U1–N7.U8)** fixes what S found on the lab laptop, and
what a full review of the other screens then found:
- **Instruments:** entry in grams, no balance field, all twenty filaments in view.
- **Pattern designer:**
  - bits are translated to the sleeve's channels on import and export (the export used to fire
    the wrong bits);
  - **Play on the real sleeve**;
  - it opens maximized and fits the laptop;
  - a clear, full-width grid, and all three modes described on screen.
- **Experimenter window:**
  - no empty 220 px banner band, so it fits a 1280×640 laptop screen (tested);
  - disabled red buttons greyed, and faults wrapped;
  - the F40 review says what is due, and the resume question reads correctly;
  - Swedish fixes, including Cancel as "Tillbaka" beside "Avbryt sessionen".

**`make check` passes:** 962 tests, ruff, the validator (34 checks) and 158 screens. The unit
tests run on at most 6 workers, because one per core made the timed session tests stall at
random (N7.U7). **An intermittent test-worker crash is pre-existing and unexplained** (N7.U7).
It struck the old `main` in 2 of 4 runs and the commit before the UI review in 3 of 9. If a run
fails only on a crashed worker, run it again.

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Screens re-approved on this branch:** the designer, Instruments, and every experimenter
  main-window state and dialog (N7.U1, N7.U2, N7.U4). Also still unreviewed: the earlier
  N7.C24 and N7.E9 sets.
- **The participant screen is 1920×1200, but its screenshots are 1280×800** (N7.H3).
- **Drafted wording:** the rows N7.U1, N7.U2 and N7.U4, and N7.C1.
- **Blinding choices:** N7.E4 and N7.D17. **Low-confidence decisions:** N7.C2, N7.B2 and N7.D8.
- **Open items still S's:** L11 (rehearsal pressure), L13 (noise ceiling and the cue), L3
  (alert metering), and new **L14**: what the experimenter does when the prototype sleeve's
  link is lost, since its outputs may stay on until it is reconnected (N7.U8).

---

## Next steps

1. **Find the pre-existing test-worker crash** (N7.U7), in a fresh session. It is a heap
   corruption (`0xc0000374`) that surfaces in whichever test next builds a window, often in
   `tests/test_protocol_a.py` or `tests/test_session_runner.py`. It strikes the old `main` too.
   A between-tests `gc.collect()` made it worse. Start from the N7.I3 class of bug: Qt objects
   outliving their windows.
2. **S reviews the re-approved screens and the drafted wording** (N7.U1, N7.U2, N7.U4). They
   are already in `main`, so a wording or layout change is an ordinary fix.
3. **S's decisions from the UI review** that change how a session runs or what the participant
   sees, so the build did not take them:
   - **"Start block" is the go button for every step** and is always enabled, and a press
     during a countdown does nothing. Rename it to a neutral "Proceed" / "Fortsätt", and enable
     it only while something waits for it?
   - **"Discard and repeat last trial" is always enabled** but does something only in a
     pinprick block. Enable it only when there is something to discard?
   - **The zone diagram** is small (about 90×150 px) and changes size when the pressures or
     faults appear. Give it a fixed, larger height?
   - **Participant screens at 1920×1200:** text, marker and line sizes are fixed, not scaled
     to the screen. Scale them to screen height, or add a 1920×1200 screenshot run?
   - **Blinding (lab layout):** the self-start screen appears only in the participant-preferred
     condition. The participant monitor must face away from the experimenter.
   - The schedule preview is in English in both languages (`tools/preview_schedule.py`).
4. **Pilot a session on the sleeve by hand**, and fix what a person finds that the validator
   cannot. In particular, try Play on the sleeve in the designer, the remote routing (N7.I1),
   and whether the alerts are audible over the noise.
5. **The VAS training screens** (§10.6, `training.*`), which nothing presents yet (SOP TBC 12).
6. **Freeze the screenshots** (`make shots ARGS="--freeze"`), once S has reviewed them.
7. **Run the adversarial review** (spec-review, §17.6) over the whole build, then merge to
   `main`.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):**
  - `arduino_valves.py` (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`, starting from `tools/garment_bits.py` and N7.H2.
