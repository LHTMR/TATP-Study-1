# STATUS

**Last updated:** 5 October 2026.
**Milestone:** 6 (pilotable), in progress. Milestones 2–5 and the Milestone 6 work up to the
UI review, plus the test-worker crash fix, are in `main`. Acceleration push under way
(`CLAUDE.md`).
**Branch:** `accel/integration`, ahead of `main` by the work below.

---

## Where things stand

**The build runs a whole session**, against the mock garment or the prototype sleeve. The garment
is chosen at launch. `run_session.py` with no arguments opens the launcher (§4.1).

**S's first lab run (30 Sep 2026) and what came of it** (`docs/LOG.md` N7.F1–N7.F4):
- **The remote's keys were swapped.** A key probe on the lab R400 showed ▶ sends `f5` and
  `escape` in turn, and "!" sends `period`. The config had them the other way round, so ▶ fired
  the emergency stop. Both of ▶'s keys now confirm, and `period` is the stop. SPEC §10.1 and the
  SOP are corrected. Most of the run's other findings follow from this: the stop screen's
  "Please wait" in audio setup, and the session advancing on random presses (N7.F1).
- **Pilot codes 901–910** each repeat participant 1–10's allocation. They are generated, so
  regenerating the file keeps them (N7.F2).
- **The first participant screen** says "The session will start shortly." (N7.F3).
- **Instruments and environment has a Close button** (N7.F3).
- **Launcher entry 5, Check the hardware.** It checks the remote's buttons, the screens, the sound
  devices with every output listed, and each garment channel, through the session's own code. It
  adds no sound level or pressure (N7.F4).

**Earlier on `accel/integration`, not yet in `main`** (N7.U10–N7.U19, N7.T1–N7.T4):
- VAS proportionality training;
- the UI-review calls;
- the validator timing fix;
- the data upload;
- the ▶ double-tap lockout;
- the lost-link log;
- the REDCap checkbox.

**`make check` passes:** 1013 tests, ruff, the validator (35 checks) and 172 screens.

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Screens to review:**
  - new: `experimenter_{en,sv}_launcher_hardware_check` and
    `participant_{en,sv}_screen_session_starting`;
  - re-approved: `experimenter_{en,sv}_launcher` and `_launcher_instruments` (N7.F3, N7.F4);
  - earlier: N7.U10, N7.T3, N7.U19, N7.U17;
  - still unreviewed: N7.U1, N7.U2, N7.U4, N7.C24 and N7.E9.
- **Drafted wording:**
  - the hardware check (N7.F4) and the Swedish "Sessionen börjar snart." (N7.F3);
  - earlier: N7.T1, N7.T2, N7.U10, N7.U16, N7.U17;
  - still unreviewed: N7.U1, N7.U2, N7.U4 and N7.C1.
- **Decisions to check:**
  - the UI-review calls (N7.U10);
  - VAS training in every session (N7.T4, R34);
  - blinding choices N7.E4 and N7.D17;
  - low-confidence decisions N7.C2, N7.B2 and N7.D8.
- **Open items still S's:** L11, the rehearsal pressure; L13, the noise ceiling and the cue; L3,
  alert metering; L14, a lost sleeve link.

---

## Next steps

1. **Re-run the lab session with the remapped remote, starting with Check the hardware.**
   - **Sound:** `audio.participant_device` is `Bose QC Headphones WASAPI`, the Bluetooth device.
     On a cable the sound goes to the laptop's own headphone output, which is a different
     device. The check lists every output by name. Set `participant_device` to whichever the
     study will use.
   - **Re-check these reports from the run**, now the keys are right:
     - the experimenter screen said "waiting for the participant's response" while the
       participant's said "Rest for a moment";
     - the participant was not told of a stop in setup.

     The code was traced and neither was found, so both may have been the swapped keys.
   - **Then the rest of the pilot checks:**
     - the participant screen on the HP at 1.5;
     - the VAS training flow;
     - the remote routing (N7.I1), including that Esc or F5 on the experimenter's keyboard now
       counts as ▶;
     - whether the alerts are audible over the noise.
2. **S reviews and merges `accel/integration` into `main`.**
3. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
4. **Run the adversarial review** (spec-review, §17.6) over the whole build before declaring
   Milestone 6 done.
5. **Left open, not blocking:**
   - the mock's injected faults never lose the link (N7.U8 (2));
   - the emergency stop does not stop the white noise.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):**
  - `arduino_valves.py` (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`, starting from `tools/garment_bits.py` and N7.H2.
