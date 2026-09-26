# STATUS

**Last updated:** 26 September 2026.
**Milestone:** 6 (pilotable), in progress. Milestones 2–5 and the Milestone 6 work up to the
UI review, plus the test-worker crash fix, are in `main`. Acceleration push under way
(`CLAUDE.md`).
**Branch:** `accel/integration`, ahead of `main` by the work below. Each piece had
`/code-review high` and spec-review before it was merged, and their findings are fixed.

---

## Where things stand

**The build runs a whole session**, against the mock garment or the prototype sleeve. The garment
is chosen at launch. `run_session.py` with no arguments opens the launcher (§4.1).

**New on `accel/integration` since `main`** (`docs/LOG.md` N7.U10–N7.U19, N7.T1–N7.T4):
- **VAS proportionality training (§10.6)**, which nothing presented before, is built. It runs
  once per scale in every session (R34). Intensity and pleasantness come at the start of touch
  calibration, and pain at pre-sensitisation. The participant sees the scale as rated. The
  experimenter explains the labels aloud and presses Next step, and only then can the
  participant dismiss it with ▶.
- **The UI-review questions, decided by the build as S asked:**
  - "Start block" is **"Next step" / "Nästa steg"**, and it stays enabled.
  - **Discard** is enabled only when there is a trial to discard.
  - The **zone diagram** has a fixed height of 180 px.
  - The **participant screen draws at the approved 1280×800** on the 1920×1200 HP
    (`screens.scale_factors`).
  - The **schedule preview** is in the experimenter's language.
  - The **SOP** tells the experimenter to sit where they cannot see past the curtain to the
    participant's display (N7.U14).
- **The validator's timing check passes again.** A trial's steps are now timed from the moment
  they follow, so slow file writes no longer add to the intervals (N7.U11).
- **The data upload:** SOP §14.2 has the experimenter upload each session to `01_raw` on LiU
  network storage and check it, and never delete the lab PC's copy. `tools/check_upload.py`
  lets S verify each upload by SHA-256 (N4.1).
- **Fixes of 26 Sep:**
  - a double tap on ▶ can no longer skip a screen unread or confirm an adjustment at its start
    (N7.U15);
  - a lost sleeve link is in the session log, and warned of in the experimenter's language
    (N7.U16);
  - the session file records whether the REDCap form was completed, from a checkbox in the
    Run a session dialog (N7.U17, SPEC §1.2);
  - a second test-worker crash is fixed (N7.U18).

**`make check` passes:** 1001 tests, ruff, the validator (35 checks) and 168 screens.

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Screens to review:**
  - re-approved: every experimenter main-window state and both schedule previews (N7.U10);
  - new: the eight VAS training screens (N7.T3) and the two lost-link screens (N7.U19);
  - re-approved: the four Run a session dialog screens, for the REDCap checkbox (N7.U17);
  - still unreviewed from earlier: N7.U1, N7.U2, N7.U4, N7.C24 and N7.E9.
- **Drafted wording:**
  - the training's continue line and experimenter instructions (N7.T1, N7.T2);
  - the schedule preview and its warnings in both languages (N7.U10), each key marked DRAFT;
  - the lost-link warning (N7.U16) and the REDCap checkbox (N7.U17);
  - still unreviewed from earlier: N7.U1, N7.U2, N7.U4 and N7.C1.
- **Decisions to check:**
  - the UI-review calls (N7.U10);
  - VAS training in every session, and where (N7.T4, R34, medium confidence);
  - blinding choices N7.E4 and N7.D17;
  - low-confidence decisions N7.C2, N7.B2 and N7.D8.
- **Open items still S's:**
  - L11: the rehearsal pressure;
  - L13: the noise ceiling and the cue;
  - L3: alert metering;
  - L14: what to do when the prototype sleeve's link is lost.

---

## Next steps

1. **S reviews and merges `accel/integration` into `main`.** `make check` passes on it.
2. **Pilot a session on the sleeve by hand**, and fix what a person finds that the validator
   cannot. In particular:
   - the participant screen on the HP at 1.5 scale;
   - the VAS training flow, with the anchors read aloud;
   - Play on the sleeve in the designer;
   - the remote routing (N7.I1);
   - whether the alerts are audible over the noise.
3. **Freeze the screenshots** (`make shots ARGS="--freeze"`) once S has reviewed them.
4. **Run the adversarial review** (spec-review, §17.6) over the whole build before declaring
   Milestone 6 done.
5. **Left open, not blocking:** the mock garment's injected faults never lose the link, so the
   validator does not exercise the lost-link path. It is unit-tested on the prototype driver
   (N7.U8 (2)).

---

## Later

- **Hardware bring-up for the valve garment (§18.2):**
  - `arduino_valves.py` (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`, starting from `tools/garment_bits.py` and N7.H2.
