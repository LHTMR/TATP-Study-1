# STATUS

**Last updated:** 25 September 2026.
**Milestone:** 6 (pilotable), in progress. Milestones 2–5 are merged and in `main`. Acceleration
push under way (`CLAUDE.md`).
**Branch:** `accel/integration`.

---

## Where things stand

**The build runs a whole session**, against the mock garment or now the prototype sleeve.
`run_session.py` with no arguments opens the launcher (§4.1): Run a session, Instruments,
Design a pattern, Preview schedule. The command line runs a session directly:

```
conda run -n tatp-study-1 python run_session.py --participant 01 --session 1 --experimenter SM --patterns config/patterns/examples
```

**Set up on the lab laptop, 25 Sep 2026** (`docs/LOG.md` N7.H1–N7.H3):
- **The prototype sleeve drives for real** through `arduino_mosfet` on COM3. The channel bits
  are mapped with S watching (N7.H2), and a live sweep was checked on the sleeve.
- **Screens:** participant on the HP (index 1), experimenter on the laptop (index 0).
- **Audio:** WASAPI at 48 kHz, the Bose headphones for the participant, the laptop speakers for
  alerts.
- **`garment.driver` is still `mock` in `hardware.yaml`.** To pilot on the sleeve, set it to
  `arduino_mosfet`. Protocol B then runs in timing-only mode with the amber banner (§12.4).

**Milestone 6 progress:** SOP.md and README.md are written (gaps marked [TBC]). The pattern
designer is merged (N7.P1). The stop rehearsal shows the remote's real "!" sticker (N7.I4, L12
closed).

**`make check` passes:** 930 tests, ruff, the validator (34 checks, 0 skipped, 18
whole-session scenarios) and 158 screens, in about 4 minutes. It runs timing-sensitive
sessions, so run it on a quiet machine: two gates at once made tests stall.

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Screens to review:** 22 new participant screens (N7.C24), 140 experimenter and launcher
  screens (N7.E9), and 12 designer screens.
- **The participant screen is 1920×1200, but the approved participant screenshots are
  1280×800** (N7.H3). Look when testing.
- **Blinding choices:** N7.E4 and N7.D17.
- **Low-confidence decisions:** N7.C2, N7.B2 and N7.D8.
- **Drafted wording:** N7.C1.
- **Open items still S's:**
  - L11, the rehearsal pressure. On the prototype it has no effect, because pressure is set by
    hand.
  - L13, whether the noise ceiling caps the cue.
  - L3, metering the alert against the noise.

---

## Next steps

1. **Pilot a session on the sleeve by hand**, with `garment.driver: arduino_mosfet`, and fix
   what a person finds that the validator cannot. In particular, try the remote routing
   (N7.I1) and check that the experimenter alerts are inaudible over the noise.
2. **Decide how a session selects the prototype driver.** Today it is an edit to
   `hardware.yaml`. A launcher field or a `--garment` option would avoid editing config on the
   lab PC; the validator and tests always use the mock.
3. **The VAS training screens** (§10.6, `training.*`), which nothing presents yet (SOP TBC 12).
4. **Freeze the screenshots** (`make shots ARGS="--freeze"`), once S has reviewed them.
5. **Run the adversarial review** (spec-review, §17.6) over the whole build, then merge to `main`.

---

## Later

- **Hardware bring-up for the valve garment (§18.2):**
  - `arduino_valves.py` (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`, starting from `tools/garment_bits.py` and N7.H2.
