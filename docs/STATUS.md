# STATUS

**Last updated:** 15 October 2026.
**Milestone:** 6 (pilotable), in progress, in lab piloting. Everything to date is in `main`.
**Branches:** each change on its own `pilot/<topic>` branch from `main`, reviewed and merged
back (`CLAUDE.md`, Committing). Open: `pilot/remote-raw-input`, L15 (the participant's stop lost
in a focused experimenter text field), the remote told from the experimenter's keyboard by
Windows Raw Input (LOG N7.D22).

---

## Where things stand

**The build runs a whole session**, against the mock garment or the prototype sleeve. The garment
is chosen at launch. `run_session.py` with no arguments opens the launcher (§4.1).

**S's 5 Oct issue list is fixed** (15 Oct 2026), in four branches, each reviewed with
code-review high and spec-review and merged into `main` with `make check` passing:
- **Audio setup** (`docs/LOG.md` N7.F6a–e):
  - step 1 says "until you can hear it easily", and the rehearsal's last line "It works at any time.";
  - **the noise could not be turned down because a press of 150–300 ms moved nothing**, and an
    R400 press lasts about 200 ms. Every press of the two-button control now moves at least one
    step. This also changes the pressure adjustment in touch calibration;
  - the "Can you still hear the garment?" screen is gone: the participant tells the
    experimenter, whose Next step starts the earplug path;
  - the stop rehearsal now comes before the masking check;
  - the stop during setup not being shown was N7.F5's repaint bug, now tested.
- **Rating scales** (N7.F7a–b):
  - "twice as far" is the experimenter's to say;
  - the participant makes a practice rating, which is never study data (R35);
  - holding a button accelerates the marker.
- **Touch calibration** (N7.F8a–c):
  - the long pause was the ramp to the next amplitude running after the 8–12 s gap; it now
    runs inside it;
  - Skip calibration, for the mock and the prototype only;
  - the experimenter sees "x/N answered".
- **General** (N7.F9a–b):
  - experimenter initials are case-insensitive;
  - the ▶ in participant text is blue.

**Earlier lab runs:** 30 Sep (N7.F1–F4: the remote's keys remapped, pilot codes 901–910, Check
the hardware) and 5 Oct (N7.F5: the repaint stall, Run a session fits the laptop).

**`make check` passes:** 1093 tests, ruff, the validator (36 checks) and 168 screens.

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Screens to review:**
  - from the 5 Oct fixes:
    - the audio screens `participant_{en,sv}_audio_setup_{find_level,mask_level}` and
      `_screen_stop_rehearsal_done` (N7.F6a, N7.F6c);
    - the VAS training screens `participant_{en,sv}_vas_training_{intensity,pain,pleasantness}`
      and the new `_vas_training_pain_practice` (N7.F7a);
    - the new `experimenter_{en,sv}_touchcal_estimation_skip` (N7.F8b);
    - every screen with a blue ▶ (N7.F9b);
  - from the earlier runs: N7.F3, N7.F4, N7.F5, N7.U10, N7.T3, N7.U19, N7.U17;
  - still unreviewed: N7.U1, N7.U2, N7.U4, N7.C24 and N7.E9.
- **Drafted wording:**
  - from the 5 Oct fixes:
    - the audio steps and warnings (N7.F6a, N7.F6c);
    - the practice line and the experimenter's training text (N7.F7a);
    - Skip calibration and "x/N answered" (N7.F8b, N7.F8c);
  - from the earlier runs: N7.F3, N7.F4, N7.T1, N7.T2, N7.U10, N7.U16, N7.U17;
  - still unreviewed: N7.U1, N7.U2, N7.U4 and N7.C1.
- **Decisions to check:**
  - free placement and log-only recording of the VAS practice (N7.F7a, R35);
  - the hold's speeds (N7.F7b);
  - the 2 s earplugs lockout (N7.F6c);
  - three ratings before Skip is offered (N7.F8b);
  - the earlier ones: N7.U10, N7.T4, N7.E4, N7.D17, N7.C2, N7.B2, N7.D8.
- **Open items still S's:**
  - L11, the rehearsal pressure;
  - L13, the noise ceiling and the cue;
  - L3, alert metering;
  - L14, a lost sleeve link;
  - **L15, the participant's stop typed into a focused experimenter text field.** Fixed in
    `pilot/remote-raw-input` (N7.D22); closes when the lab check N2.10 passes.

---

## Next steps

1. **Re-run the lab session, starting with Check the hardware.**
   - **Sound:** `audio.participant_device` is `Bose QC Headphones WASAPI`, the Bluetooth
     device. On a cable the sound goes to the laptop's own headphone output, which is a
     different device. Set `participant_device` to whichever the study will use.
   - **The 5 Oct fixes, in the lab:**
     - the noise turns down with single presses in step 2;
     - the stop rehearsal comes first, and the masking step's "tell the experimenter" flow
       works, including the earplug path;
     - in the 5 Oct log, check `noise_level_confirmed find_level`. If it was −60.0 dBFS, the
       participant was at the control's floor, which is audible at the lab volume (N7.F6b, L3);
     - **R400 hold check (N7.F7b):** hold a large button on a VAS. The marker should start
       slowly and speed up, and a tap should move one step. If the hold does not accelerate,
       log one key-probe hold with stamps and widen `vas.hold_regrip_max_s`;
     - the VAS practice rating, and "twice as far" said by the experimenter;
     - in touch calibration, whether the pause between touches still feels long now that the
       ramp runs inside the gap (R32's criterion before shortening it), Skip calibration, and
       "x/N answered".
   - **Then the rest of the pilot checks:**
     - the participant screen on the HP at 1.5;
     - the remote routing (N7.I1), including that Esc or F5 on the experimenter's keyboard
       counts as ▶;
     - whether the alerts are audible over the noise;
     - taps on the adjustment are never lost or misread (N2.9).
2. **L15:** merge `pilot/remote-raw-input` once its re-review findings are fixed and
   `make check` passes on a quiet machine (other sessions' test runs at 99% CPU stall `main`'s
   own code too), then run the lab check N2.10 with the R400 and the laptop keyboard. If that
   fails, `responder.key_source: any_keyboard` restores the old routing.
3. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
4. **Run the adversarial review** (spec-review, §17.6) over the whole build before declaring
   Milestone 6 done.
5. **Left open, not blocking:**
   - the mock's injected faults never lose the link (N7.U8 (2));
   - the emergency stop does not stop the white noise;
   - the hold-acceleration integral is duplicated in `VasState._travel` and
     `touchcal.AdjustmentState` (N7.F7b). Merge them;
   - **the screenshot tolerance (0.2 %) hides glyph-sized changes:** the blue ▶ passed it
     unchanged. Compare exactly when a change is that small;
   - `--approve-matching` keeps only the last pattern given, so name one per run;
   - under heavy load (several `make check` runs at once) the validator's `rates_randomly` can
     miss its 120 s limit, and session-runner tests can stall in setup. Both pass on a quiet
     machine. Run one gate at a time.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):**
  - `arduino_valves.py` (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`, starting from `tools/garment_bits.py` and N7.H2.
