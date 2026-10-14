# R35 — Should the stimulus-free VAS practice rating be free placement or placement at a target, and where is it recorded?

**Asked:** 2026-10-14. **For:** `docs/SPEC.md` §10.2 (VAS behaviour), §10.6 (VAS training), §11 (experimenter screen), §14.2 (`log` table). **Confidence:** medium

No study was found that tests a stimulus-free practice rating against a targeted one, so this
report has no direct evidence. The recommendation rests on four things: the spec's own reasoning
about production and estimation, evidence that pain ratings depend on context, evidence that
training with a target and feedback changes later reports, and the fact that the experimenter
cannot see rating values. Poulton 1995 and Watkinson et al. 2013 could be read only as
abstracts.

## The question

The proportionality training (§10.6) is gaining a practice rating, so that the participant
operates the remote once before real data are collected. The remote works as §10.2 describes:
the marker is hidden until the first press, appears at 25 % or 75 %, is moved with hold-to-repeat
and is confirmed with play. No stimulus is given. The spec does not say what the participant
aims at, or whether and where the result is stored. Both choices touch what is measured, for
two reasons:

- the practice comes immediately before the first real ratings on each scale;
- in touch calibration, the intensity ratings define the delivered pressures. The estimation
  run is fitted and inverted for P20, P30 and P80 (§9 step 2), and the sham condition is
  defined at 20 % intensity (§12).

## What the evidence says

1. **Pain ratings are relative to the context the participant has just been given.** With
   pressure pain, the same stimulus was rated higher in a context where it ranked higher, and
   ratings rose when most stimuli in the context were intense even though the mean was held
   constant. This fits range-frequency theory (Watkinson, Wood, Lloyd & Brown 2013, *Pain*
   154:743–749, [doi:10.1016/j.pain.2013.01.016](https://doi.org/10.1016/j.pain.2013.01.016),
   [repository record](https://dspace.stir.ac.uk/handle/1893/12121); *abstract only*). This
   concerns experienced stimuli, not a practice target, but it shows that the reference frame in
   which ratings are made can be moved.

2. **Material presented before an investigation starts is a recognised source of bias in
   magnitude judgements.** Poulton describes "three additional sources of bias, all involving
   the influence of stimuli presented before the start of an investigation" (Poulton 1995,
   *Behav Brain Sci* 18:604–605,
   [doi:10.1017/S0140525X00040061](https://doi.org/10.1017/S0140525X00040061); *abstract
   only*, so which three biases, and how large they are, is unconfirmed). His broader catalogue
   includes transfer bias and centring bias (Poulton 1979, *Psychol Bull* 86:777–803,
   [doi:10.1037/0033-2909.86.4.777](https://doi.org/10.1037/0033-2909.86.4.777); *known
   from secondary citations only*).

3. **Numerical anchors shift pain judgements.** An unrelated number (a wheel stopping on 8 or
   2) shifted later 0–10 ratings of a vignette patient's pain in both directions (n = 385)
   ([JMIR Hum Factors 2020;7(1):e17533](https://humanfactors.jmir.org/2020/1/e17533),
   [PMC7091028](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7091028/)). These were
   observer ratings, not self-ratings of a felt stimulus, so this supports only the direction
   of the risk, not its size here.

4. **A previously seen mark changes later VAS marks.** Patients who could see their earlier VAS
   scores rated pain differently from those who could not, and the difference grew over time
   (Scott & Huskisson 1979, *Ann Rheum Dis* 38:558–559,
   [doi:10.1136/ard.38.6.558](https://doi.org/10.1136/ard.38.6.558),
   [PMC1000419](https://pmc.ncbi.nlm.nih.gov/articles/PMC1000419)). A practice position that
   the participant has been asked to reach and remember is a remembered mark. The hidden
   marker in §10.2 already prevents a *visible* carry-over.

5. **Training with targets and feedback changes how people report.** "Accurate pain reporting
   training", which gave feedback on how well ratings tracked mechanical stimuli, raised
   participants' R² and lowered the later placebo response (Treister et al. 2018, *PLoS ONE*
   13:e0197844, [doi:10.1371/journal.pone.0197844](https://doi.org/10.1371/journal.pone.0197844),
   [PMC5993117](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5993117/)). A target practice that
   checks the participant's placement is a small instance of this kind of intervention. That is
   more than "learn the buttons", and Bilaga 1 does not describe it, as far as the spec shows.

6. **Producing a target position is a different task from estimating a magnitude.** The spec
   already relies on this: adjusting to a target is magnitude *production*, the outcomes are
   magnitude *estimation*, and the two differ systematically, which is the regression effect
   (§9, citing Teghtsoonian & Teghtsoonian 1978). A targeted practice rehearses production. It
   also lands on positions that matter downstream: "twice as painful as just painful" is 20 %,
   and so is the sham intensity target (§12). The analogous practice for intensity, "twice as
   intense as just noticeable", would rehearse a mark at exactly the level that defines sham
   pressure.

7. **Published familiarisation without a stimulus uses the participant's own judgement, not a
   target.** In the gLMS orientation, participants rated *remembered* sensations from a
   different modality ("the loudest thunder clap s/he can remember, a purring cat held in
   her/his lap, and a lawnmower across the street"). Correct rank order was the only check, and
   those ratings were kept as possible covariates for scale use (Cruickshanks et al. 2009,
   *Ann N Y Acad Sci* 1170:543–552,
   [doi:10.1111/j.1749-6632.2009.04103.x](https://doi.org/10.1111/j.1749-6632.2009.04103.x),
   [PMC2729771](https://pmc.ncbi.nlm.nih.gov/articles/PMC2729771/)). Where digital-VAS studies
   do use a target ("enter exactly 31"), it is a precision check on a numbered slider, kept
   apart from the construct items (Cloos et al. 2025, *Collabra: Psychology* 11(1):142735,
   [doi:10.1525/collabra.142735](https://doi.org/10.1525/collabra.142735)). TATP's line carries
   no numbers.

8. **A target buys no verification here.** The experimenter screen never shows rating values
   (§11, §16). Checking a target practice would need one of two things:
   - showing the value to the experimenter, which breaks a standing rule;
   - giving the participant feedback, which is finding 5's intervention.

   Without either, a target adds the anchoring exposure and none of the check.

## Options

**A. Free placement, no target, no feedback.** The participant presses either button, moves
the marker, and confirms wherever they like.
- *Cost:* it does not test whether the participant understood the ratio rule. The training
  itself covers that, by spoken explanation.
- *Risk:* a self-chosen position may act as a weak, self-generated anchor. It carries no meaning,
  though, because nothing was felt. It varies at random between participants and sessions, so at
  worst it adds noise rather than a shared bias. It is identical in procedure across sessions and
  conditions (R34), so it cannot leak condition.

**B. Target at a labelled anchor** (for example, "just painful", 10 %).
- *Cost:* new wording, and it cannot be verified (finding 8).
- *Risk:* it rehearses production at a labelled point. For intensity, it duplicates the §9
  step 1 adjustment that follows. The bias is small but systematic and has no counterweight.

**C. Target at a described hypothetical intensity** (for example, "twice as painful as just
painful", 20 %).
- *Cost:* the same as B, plus a computed position the participant must imagine.
- *Risk:* it is the most direct anchor (findings 2, 3, 4 and 6). It rehearses an unlabelled
  interior position, which §9 calls "a different and worse task". For intensity it coincides
  with the sham's defining level, so any assimilation enters the delivered pressures through the
  P20 fit.

**D. Rate a remembered or imagined sensation** (gLMS-style). Rejected. On the pain scale it
asks the participant to think about pain intensity just before the baseline pinprick ratings,
which plants an expectation. On a scale labelled for pain or touch, a different modality is
incoherent. It also needs new participant wording.

**Recording.**
- *(i) Not recorded.* This loses the provenance of what the participant did, and the pilot
  check below.
- *(ii) `log` only.*
- *(iii) A separate practice table.* This is a table for one row per scale per session.
- *(iv) A ratings table with a flag.* This is the one way it can be mistaken for data.

## Recommendation

**Option A, recorded in the `log` table only.** The practice exists to teach the remote, and free
placement does that without adding a reference point on the scale. Every targeted variant puts
a production rehearsal at a position the analysis or the pressure calibration later depends on.
None of them can be checked without either showing a rating value to the experimenter or giving
the participant feedback.

Two points for the main session to settle in its own wording:

- **Make the practice exercise both buttons.** The practice is about operating the remote, so
  it would ideally ask the participant to move the marker both ways before confirming. That
  gives exposure to both ends, which are already labelled, rather than to one interior point.
- **Say plainly that the practice is not a rating.** The participant should understand that the
  practice is "just to try the buttons", not a rating of anything.

The wording is the main session's to write. I have written none.

**Recording.** Add practice events to `log` beside the existing `vas_training_*` events, with
the scale in `detail`. For example:
- `vas_practice_shown`;
- the first-press side, as §10.2 already logs for real ratings;
- `vas_practice_confirmed`, with origin `participant` and the confirmed position in `detail`.

Never write a practice row to `pinprick`, `touch_ratings`, `touchcal_estimate` or any other
ratings table. A `validate_session` assertion could enforce this, by checking that no ratings
row for a scale comes before that scale's practice confirmation in the session. The experimenter
screen should show only that the practice was completed, never the position (§11). Keep the
position because it costs nothing, and because it is the only way to run the pilot check below.
It is not an outcome.

The practice should run wherever the training runs, identically in every session (R34). This
keeps it condition-blind by construction, so §16 is unaffected.

## What would change this

- **Pilot data.** Suppose the practice position predicts the first real rating on that scale in
  the same session more strongly than it predicts later ratings (within participant, across
  sessions). Free placement would then be acting as an anchor. The remedy would be a practice on
  a neutral, unlabelled line, not a target.
- **Operational failure.** Suppose participants still show `confirm_without_marker`, or long
  latencies, at their first real rating despite the practice. The practice would then need more
  movement, not a target.
- **Bilaga 1 or the application describes a targeted practice.** In that case follow it, or
  record the deviation in `docs/LOG.md`.
- **Full text of Poulton 1995 or 1979** quantifying bias from pre-investigation examples on a
  bounded line.

## To fetch

| DOI | Title | Why |
|---|---|---|
| 10.1017/S0140525X00040061 | Poulton 1995, Bias by stimuli presented before the start of an investigation | Which three biases, and how large; abstract only |
| 10.1037/0033-2909.86.4.777 | Poulton 1979, Models for biases in judging sensory magnitude | Transfer and centring bias; known only from citations |
| 10.1016/j.pain.2013.01.016 | Watkinson et al. 2013, Pain ratings reflect cognitive context | Effect sizes of context on pain ratings; abstract only |
