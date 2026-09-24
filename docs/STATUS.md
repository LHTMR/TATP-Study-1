# STATUS

**Last updated:** 24 September 2026.
**Milestone:** 6 (pilotable), next. Milestones 2–5 are merged and in `main`. Acceleration push
under way (`CLAUDE.md`).
**Branch:** `accel/integration`.

---

## Where things stand

**The build is lab-testable with the mock garment.** `run_session.py` with no arguments opens
the launcher (§4.1). There, Run a session takes the session details, runs the preflight, offers
resume, and runs the whole session. Named on the command line, it runs the same session
directly:

```
conda run -n tatp-study-1 python run_session.py --participant 01 --session 1 --experimenter SM --patterns config/patterns/examples
```

The session runs, in order:
- **Setup:** masking check, stop rehearsal, touch calibration.
- **The three pain time points:** long, short and brush, with mapping at post-S and post-I.
- **Sensitisation and capsaicin**, timed.
- **The intervention:** twelve experimenter-launched blocks around the rekindle, with the
  garment delivering the allocated condition.
- **Crash recovery** through all of it.

**`make check` passes:** 760 tests, ruff, the validator (34 checks, 0 skipped, 18 whole-session
scenarios) and 146 screens. It now takes about 4–5 minutes (`docs/LOG.md` N7.D20).

**For S, before the pilot.** Everything is in `docs/LOG.md` §7:
- **Screens:** 22 new participant screens (N7.C24), and 140 experimenter and launcher screens
  (N7.E9), 70 per language.
- **Blinding choices:** N7.E4 hides channel detail during the intervention; N7.D17 makes the
  touch-start timing identical in every condition.
- **Low-confidence decisions:** N7.C2, the stage-1 gate numbers; N7.B2 and N7.D8, the prior
  offsets.
- **Drafted wording:** N7.C1.
- **Open items for S:**
  - L12: the stop-button symbol, which currently shows `PLACEHOLDER` on the rehearsal screen.
  - L11: the rehearsal pressure.
  - L13: whether the noise ceiling also caps the cue.
  - L10: the audio devices.

---

## Paused, 24 Sep 2026 — pick up here

- **Pattern designer**, on branch `accel/pattern-designer` (reviewed at `777701e`). It is not merged. A
  stream agent was fixing the code-review findings in its worktree
  (`.claude/worktrees/agent-adc72f6d445f361a6`) when the session paused. Check that worktree for
  uncommitted work first. If the fixes are not all committed, finish them: lossless number
  display, finite intervals (also in `patterns.from_text`), one designer window, invalid ids
  disable the actions, sidecar comments kept on re-save, re-save to the opened path,
  reference-CSV edge cases, the file-open errors shown as messages, and `mask_bits` moved into
  config. Then run `make check`, merge into `accel/integration`, add LOG rows N7.P1 and on
  (from the stream's report), and correct N7.E6 (the designer entry is no longer disabled).
- **Done since the last status:**
  - SOP.md and README.md are merged, with gaps marked [TBC].
  - The remote reaches the participant window whichever window is active (N7.I1).
  - The stop symbol is a red circle (N7.I2).

## Next steps

Milestone 6 (§18):

1. **Run a real session on the lab PC.** Go through it by hand with the mock garment and fix
   what a person finds that the validator cannot.
2. **Write `SOP.md` and update `README.md`.** The SOP covers:
   - the lab session step by step;
   - the manual data transfer (N4.1);
   - what each banner and alert means.
3. **The pattern designer** (§12.2, launcher entry 3), which is still disabled. Also the VAS
   training screens (§10.6, `training.*`), which nothing presents yet.
4. **Freeze the screenshots** (`make shots ARGS="--freeze"`), once S has reviewed them.
5. **Run the adversarial review** (spec-review, §17.6) over the whole build.

---

## Later

- **Hardware bring-up (§18.2):**
  - the real drivers (open item 14);
  - the rate limit (L2) and the inflation rates (item 3);
  - `HARDWARE_BRINGUP.md`.
