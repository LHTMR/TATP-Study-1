# R36 — What re-calibration of the touch to offer when resuming from an emergency stop, in each phase

**Asked:** 2026-10-15. **For:** `docs/SPEC.md` §9, §10.9, §12.3, §13, §15, §16. Pilot feedback of
15 Oct 2026 ("when resuming from emergency stop, need to have the option to re-calibrate
channels"). **Confidence:** medium. The touch-calibration part is medium-high, because it only
reuses re-run paths that already exist. The intervention part is medium: the reasoning is
strong, but the evidence is indirect, and two of the sources could be read only as abstracts.

## The question

Today the only way out of a software emergency stop is **Resume** (`tatp/interruption.py`).
Resume restores the pressures and pattern that were in force before the stop, after the warning
cue, and the running procedure then repeats the step it abandoned. So a participant who pressed
stop because one channel felt wrong (too strong, uncomfortable, uneven along the arm) gets the
same touch back. S asked for an option to re-calibrate.

The spec does not settle this:

- §13 requires that resumption be "genuinely clean", and Bilaga 1 §3.10 promises that pressing
  the stop "will not disturb the experiment".
- §9 and LOG N7.C8 define two re-run paths inside touch calibration, both reached from other
  triggers:
  - the **rebalance** (steps 3–4 again, from the evenness check, capped by
    `evenness_max_rebalances`);
  - the **re-run of steps 1–2** (from the stage-1 gate or the fit preview, capped by
    `fit_preview.max_reruns`, the discarded run kept `superseded`).
- Nothing says whether either may be reached from a stop, or whether anything may be
  re-calibrated once the intervention has started.

The design of Protocol B is settled (`docs/calibration_methods_comparison.md` §7) and is not
re-opened here. This report covers only what is re-run after a stop, where, and how it is
recorded.

## What the evidence says

**No published protocol covers this exact case.** I found no QST, CT-touch or psychophysics
protocol, and no reference implementation, that describes re-calibrating a touch device after a
participant-initiated stop. I searched only briefly for reference implementations (PsychoPy's
eye-tracker setup procedure offers re-calibration between trials, but I found it documented only
on forums, which do not count as a source here). What follows is therefore built from evidence
about the measurement, not from precedent.

**1. The skin under the garment is not the same skin during the intervention.** Touch
calibration runs before sensitisation. The intervention runs on the same arm after heat and
capsaicin.

- In the heat/capsaicin model, a 45 °C, 5 min thermode plus 30 min of capsaicin cream produces
  secondary hyperalgesia. Periodic re-heating ("rekindling") maintains it for about 4 h
  (Petersen & Rowbotham 1999, *Neuroreport* 10:1511–1516, PMID 10380972,
  [doi:10.1097/00001756-199905140-00022](https://doi.org/10.1097/00001756-199905140-00022);
  abstract only, via Europe PMC).
- In the neurogenic (intradermal capsaicin) model, the area tender to **gentle stroking** was
  about 38 cm² and disappeared within 1–2 h. The punctate-hyperalgesia area was larger, about
  55 cm², and lasted 13–24 h (LaMotte et al. 1991, *J Neurophysiol* 66:190–211,
  [doi:10.1152/jn.1991.66.1.190](https://doi.org/10.1152/jn.1991.66.1.190); abstract only).
  This is a different model from the one TATP uses. The point that carries over is that the
  sensitivity to moving, stroking-like touch changes within the timescale of the intervention.
- In the heat/capsaicin model, healthy participants reported **tactile-evoked pain** from
  stroking in the allodynic zone. The authors conclude that dynamic tactile allodynia goes with
  "reduced CT mediated hedonic touch processing" (Liljencrantz et al. 2013, *Pain* 154:227–234,
  read through the authors' open-access review: Liljencrantz & Olausson 2014,
  *Front Behav Neurosci* 8:37,
  [doi:10.3389/fnbeh.2014.00037](https://doi.org/10.3389/fnbeh.2014.00037)). The 2013 primary
  paper itself was not read.

What this means for re-calibration: a calibration run during the intervention would measure the
touch on sensitised skin. Every session's main calibration is run on unsensitised skin. The two
are not the same measurement. Part of what a mid-intervention re-calibration would "correct" is
the sensitisation itself, and that is close to what the study measures.

**2. Changes in how the touch feels over the intervention are themselves an outcome, and they
differ between conditions.** Repeated brush stroking on the forearm for about 50 min lowered
pleasantness and wanting ratings slowly. The decline was larger at a CT-optimal 3 cm/s than at
0.3 or 30 cm/s (Triscoli, Ackerley & Sailer 2014, *PLoS One* 9:e113425,
[doi:10.1371/journal.pone.0113425](https://doi.org/10.1371/journal.pone.0113425),
[PMC4236195](https://pmc.ncbi.nlm.nih.gov/articles/PMC4236195/)).

TATP's three conditions also differ in what is delivered:

| Condition | Pattern | Level |
|---|---|---|
| sham | static | P20 |
| ct_targeted | the CT sweep | pleasant level |
| participant_preferred | the participant's chosen pattern | pleasant level |

(`TouchCalibrationResult`, R31.) So a stop for discomfort during the intervention is likely to be
more common in some conditions than in others. Any re-calibration it triggers would then fall
unevenly across conditions. The screens would show nothing, so it would be blinding-neutral on
screen, but it would not be neutral for the measurement.

**3. The intervention clock cannot be paused.** The hyperalgesia runs on its own clock from
sensitisation and is kept up by rekindles at fixed times (Petersen & Rowbotham 1999). SPEC §7.4
anchors everything to session t=0 and never shifts the schedule. A re-calibration therefore
cannot be slotted in "outside" the intervention. Every minute it takes is a minute without the
condition's touch, and scheduled blocks keep falling due during it.

The cost would be:

- **Rebalance (steps 3–4 plus the evenness check):** from the comparison document's §7.2
  figures, roughly 8 matching adjustments plus at least 8 comparisons, about 6–9 min.
- **Full restart (steps 1–6):** about 10.6–14.5 min.

**4. A re-calibration delivers touch that is not the condition's.**

- Steps 3–4 are static 3 s holds at the match level on every channel.
- The evenness check plays the fixed CT sweep (`sweep_03cms`, LOG N7.C14) at the pleasant level.
- In a sham session, that puts CT-targeted touch into the sham condition's window.
- A restart from step 1 also asks for the 90 % "just uncomfortable" bracket again, now on
  sensitised skin. That is a safety question, and it is S's (see the end).

**5. The interaction around a re-calibration is itself a non-specific influence on pain.** In
the IBS placebo trial, an augmented practitioner interaction produced the largest effect on the
outcome. The authors conclude that "the patient–practitioner relationship is the most robust
component" of the non-specific effects (Kaptchuk et al. 2008, *BMJ* 336:999–1003,
[doi:10.1136/bmj.39524.439618.25](https://doi.org/10.1136/bmj.39524.439618.25),
[PMC2364862](https://pmc.ncbi.nlm.nih.gov/articles/PMC2364862/)). An experimenter who stops and
adjusts the touch because the participant complained is exactly such an interaction. It would
appear only in some sessions, and those sessions would not be spread evenly across conditions
(point 2).

**6. How analysis should treat a change of treatment mid-condition.** The estimands framework
calls a post-randomisation event that changes the treatment received a "treatment-modifying"
**intercurrent event**. It requires a strategy for each anticipated type to be set in advance,
and notes that "data collection has an essential role in determining which estimands can be
estimated" (Kahan et al. 2024, *BMJ* 384:e076316,
[doi:10.1136/bmj-2023-076316](https://doi.org/10.1136/bmj-2023-076316),
[PMC10802140](https://pmc.ncbi.nlm.nih.gov/articles/PMC10802140/), a primer on ICH E9(R1)).

Two consequences:

- A stop during the intervention is an intercurrent event whatever is done next, so it must be
  recorded in a form analysis can find.
- A re-calibration would turn the condition into "touch A, then a calibration, then touch B".
  That is a modified treatment, which analysis can only discard, model or ignore.

**7. Forking paths.** SPEC §11.1 already holds that a procedure repeatable until it looks right
is a garden of forking paths unless every attempt is retained. The same applies to re-runs
reached from a stop: they must be kept, marked and capped.

## Options

**A. No change: Resume only, everywhere.** Costs nothing. *Risk:* a participant who stopped
because a channel felt wrong during calibration gets the same calibration back. That calibration
then defines every delivered pressure for the session. The pilot showed this is a real need.
Rejected for touch calibration.

**B. In touch calibration only, offer the two existing re-run paths at the resume. Elsewhere,
Resume as now. (Recommended.)** After a stop *during touch calibration*, the experimenter
chooses one of:

- **Resume:** repeat the abandoned step. This is the default.
- **Rebalance channels:** steps 3–4 again, then the evenness check, then on. This is exactly the
  N7.C8 path.
- **Restart calibration:** a new run from step 1. The earlier run is kept and superseded.

*Cost:* one experimenter choice screen and two entry points into code that already exists.
*Risk:* small. Calibration is identical in every condition and comes before anything is
measured, so a re-run costs only time, and the earlier attempt stays in the data.

**C. As B, plus a re-calibration offer during the intervention (rebalance, or restart).**
*Risks:* points 1–6.

- It calibrates on sensitised skin, unlike every other calibration.
- It cannot pause a clock that is physiological.
- It removes 6–15 min of the condition's touch and inserts non-condition touch, including CT
  touch in sham sessions.
- It would occur unevenly across conditions, which makes it non-neutral for measurement even
  though the screens stay blind.
- A restart re-exposes sensitised skin to the "just uncomfortable" bracket.

It can be made blinding-neutral on screen, because the offer and the procedure are the same in
every condition. It cannot be made measurement-neutral. Rejected.

**D. During the intervention, lower only the offending channel (or all channels) by some step,
then resume.** This is the simplest thing that answers "it felt too strong". It delivers no
non-condition touch and takes seconds.

*Risks:*

- It is still a within-condition change of treatment, an intercurrent event.
- How much to lower, and whether lowering below the calibrated level is permitted, is a
  delivered-pressure and safety rule. That is **S's decision**, and this report does not propose
  a value.
- It is driven by complaints, which differ by condition (point 2).
- Lowering one channel unbalances the evenness that steps 3–4 established.

Recorded here as S's to decide, not recommended.

**E. During the intervention, offer "continue with the touch off for the rest of the session".**
This is cleaner for analysis than D: the intercurrent event is a discontinuation, which the
estimand framework handles directly ("while on treatment", or treat the session as a protocol
deviation), and the remaining pain measures are still collected. It must be offered identically
in every condition (§16). Whether a participant may continue the session without the touch is a
protocol decision for **S**, not a re-calibration question. Noted, not recommended here.

## Recommendation

**Option B.** Re-calibration after a stop is offered **only during touch calibration**. Every
other phase keeps the current Resume.

The phases, one by one:

1. **Touch calibration (steps 1–6 and the evenness check).** At the resume, the experimenter
   chooses Resume, Rebalance channels or Restart calibration.
   - **Rebalance channels** is offered only once step 2's fit has been accepted, because steps
     3–4 need the reference targets. It re-runs steps 3–4 for all four test channels from the
     original two start points (R33), then the evenness check, then step 6. If step 5 was
     already done, the pleasantness level stands, as in N7.C8: it is on the reference's scale,
     which the gains do not touch.
   - **Restart calibration** starts a new run (`run_index` + 1) from step 1. The scale training
     is not repeated (it is already given). The earlier run's fit row is written `superseded`
     with `rerun_reason` saying it followed a stop.
   - **On either re-run, the snapshot is not restored.** The garment stays at zero, and the
     chosen procedure starts with its own cue.
   - **A stop during step 1's 90 % "just uncomfortable" adjustment is to be expected.** Plain
     Resume, which repeats the adjustment, is the right default there.
   - I considered and did **not** recommend a third path, "re-run step 5 only", for "the whole
     thing is too strong" during step 6. Step 5 is already bounded to [P30, P80] and set by the
     participant. An overall level that is wrong points at the fit, and Restart covers that.
2. **Setup: stop rehearsal and masking check.**
   - **No offer.** Both run a fixed pressure that nothing calibrates, so there is nothing to
     re-run.
   - The rehearsal's stop is the point of the rehearsal.
   - If the fixed pressure itself is uncomfortable, that is open item L11 or the masking
     pressure, which is S's.
3. **Phases with the garment off** (baseline ratings, pre-sensitisation, sensitisation,
   post-sensitisation, post-intervention). No offer: there is no touch to re-calibrate.
4. **The intervention** (continuous delivery, touch blocks, reactivation after the rekindle).
   - **No re-calibration.** Resume restores the condition's touch exactly, as now.
   - The stop is recorded as an intercurrent event, below.
   - Whether a participant who cannot tolerate the condition's touch may continue with it
     lowered (D) or off (E) goes to **S**.
   - A re-calibration here cannot be made acceptable for the measurement (points 1–6). It also
     cannot be made acceptable by pausing the intervention clock, because the clock is the
     sensitisation's, not the software's.

**Recording.**

- Every resume after an emergency stop writes a `log` row with:
  - the experimenter's choice (`resume`, `rebalance`, `restart`), with `origin="experimenter"`;
  - the phase, and the calibration step that was abandoned.
- Re-runs use the identifiers that already exist:
  - `pass_index` on `touchcal_adjust` for a rebalance;
  - `run_index` and `superseded`, with a `rerun_reason`, on `touchcal_fit` for a restart.
- `touchcal_channels` is written once, at the end, so it holds only the calibration actually
  used. The earlier attempt survives in the per-step tables and the superseded fit row. Crash
  recovery (`tatp/resume.py`, which reads the last `touchcal_channels` set) needs no change.
- The session file should carry a count of emergency stops **during the intervention**, so
  analysis can find those sessions without parsing the log.

**Reason.** Required, as one choice from a short fixed list that the main session writes (in
substance: a channel felt wrong or uneven; it was too strong overall; other), plus the existing
free-text note if wanted. This is experimenter-facing wording, so it is not under the
participant rules, but the main session drafts it.

A fixed list costs one press, can be analysed, and says nothing about condition: calibration is
identical in every condition, and no rating value is shown.

**Cap.** At most **one stop-triggered re-calibration per session**, as a new config value
(suggested name `touch_calibration.recalibrations_after_stop_max: 1`). It is kept separate from
`evenness_max_rebalances` and `fit_preview.max_reruns`, so that the source of each re-run stays
legible. Once the cap is used up, only Resume is offered and the screen says why.

A second stop that needs re-calibration in the same calibration is a signal about the hardware
or the fit, and S should see it. More loops will not fix it. The reasoning is the same as R33's
single re-adjustment pass.

**Blinding (§16).** All of this happens in touch calibration, which is identical in every
condition, before the condition is used. The offer appears whatever the condition. Nothing in
this recommendation weakens blinding.

## What would change this

- **Pilot stops during the intervention, clustered in one kind of complaint**, for example "too
  strong at channel *n*". That would be a finding about the calibration: the transfer from the
  3 s hold, the P80 upper bound, or allodynia under part of the garment. It should be fixed
  **between sessions** in the calibration design (comparison doc §7.4's pulse-timing option), not
  within a session. If such stops are frequent, S's decision on D or E becomes urgent.
- **Evidence that pneumatic pressure on heat/capsaicin-sensitised forearm skin feels much as it
  did before sensitisation.** Then point 1 weakens. Points 3–6 still stand, so C would remain
  rejected.
- **Pilot sessions where the stop-triggered rebalance is used often and changes the gains
  little.** Then the stops were not about balance, and Restart or a plain Resume would serve.
  Reconsider whether the rebalance needs to be on the menu at all.
- **Reading Liljencrantz et al. 2013 in full.** If CT-optimal stroking stayed pleasant in the
  allodynic zone at the pressures TATP uses, point 1 would weaken, but not the recommendation.

## For S (not decided here)

- **Hardware and safety:**
  - whether, and by how much, a channel may be lowered below its calibrated level during the
    intervention (option D);
  - whether a restart from step 1 would ever be acceptable on sensitised skin, given that it
    asks for "just uncomfortable" again. This report recommends that it is not offered there.
- **Protocol:** whether a participant may continue the intervention with the touch off
  (option E), and how analysis treats that session.
- **Bilaga 1 §3.10.** The promise that the stop "will not disturb the experiment" holds under
  this recommendation in every phase. Nothing about the session changes because of a stop
  except, during calibration, an optional re-run.
