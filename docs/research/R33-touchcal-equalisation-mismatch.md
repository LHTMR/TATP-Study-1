# R33 — What counts as a mismatch in the Protocol B equalisation check, and how re-adjustment loops

**Asked:** 2026-09-23. **For:** `docs/SPEC.md` §9 step 4, §10.8; `docs/calibration_methods_comparison.md`
§7.2, §7.3, §7.4 / Milestone 3 (touch calibration). **Confidence:** medium

## The question

Step 4 checks each of the four matched forearm channels against the reference (channel 3) with
two forced-choice trials, one per order (`test_first`, `reference_first`), each stimulus a 3 s
hold at the matched pressures, answered "which felt stronger" with no "equal" option. The spec
says "prompt re-adjustment on mismatch" and stops there. Three things are undefined:

1. which response pattern counts as a mismatch;
2. whether the comparisons are re-run after a re-adjustment, and how many passes are allowed
   before the procedure continues with a logged warning;
3. whether a re-adjustment is one method-of-adjustment (MoA) trial or two, from both start
   points, as the original match was.

The design itself (reference-based check, both orders, 3 s hold, 2AFC with no tie) is settled in
the comparison document and is not re-opened here.

## What the evidence says

**Order effects in successive comparison are real, common, and vary in sign between people.**

- Hellström's review classes the time-order error (TOE), the systematic asymmetry between
  judging A-then-B and B-then-A, as a perceptual effect, predicted by adaptation-level theory
  and sensation weighting. It is not a response-bias artefact that can be instructed away
  (Hellström 1985, *Psychol Bull* 97:35–61,
  [doi:10.1037/0033-2909.97.1.35](https://doi.org/10.1037/0033-2909.97.1.35); abstract only,
  via [ERIC](https://eric.ed.gov/?id=EJ314283)). Space-order effects of the same kind appear
  when the two stimuli are at different positions, which is the case here: test and reference
  are different forearm sites (Hellström 2003, *Percept Psychophys* 65:1161–1177,
  [doi:10.3758/BF03194842](https://doi.org/10.3758/BF03194842); abstract only).
- In two-interval forced choice, interval bias is the rule rather than the exception. Yeshurun,
  Carrasco & Maloney reanalysed several datasets and ran their own experiment. In their own data
  8 of 22 observers showed marked bias, and in one reanalysed dataset 24 of 56 did. They conclude
  that "2-IFC in many applications is not bias free or approximately so" (2008, *Vision Res*
  48:1837–1851, [doi:10.1016/j.visres.2008.05.008](https://doi.org/10.1016/j.visres.2008.05.008),
  [PMC5839130](https://pmc.ncbi.nlm.nih.gov/articles/PMC5839130/)). García-Pérez &
  Alcalá-Quintana likewise find order effects "strong and prevalent" in 2AFC
  (2011, *Atten Percept Psychophys* 73:2332–2352,
  [doi:10.3758/s13414-011-0167-x](https://doi.org/10.3758/s13414-011-0167-x); abstract only),
  and show that adaptive procedures ignoring them give badly biased estimates (2020, *Behav Res
  Methods* 52:2168–2187, [doi:10.3758/s13428-020-01384-6](https://doi.org/10.3758/s13428-020-01384-6);
  abstract only).
- **Tactile intensity specifically.** In a vibrotactile intensity-comparison task with a 1 s
  gap, about half of 16 participants showed significant order asymmetries. Of those, roughly
  half were more accurate with the weaker stimulus first and half with the stronger first
  (Avetta et al. 2026, arXiv preprint, [arXiv:2604.19662](https://arxiv.org/abs/2604.19662); not
  peer-reviewed). In humans comparing fingertip vibrations, the first stimulus's memory trace
  drifts toward the mean of recent stimuli, a contraction bias (Fassihi et al. 2014, *PNAS*
  111:2331–2336, [doi:10.1073/pnas.1315171111](https://doi.org/10.1073/pnas.1315171111),
  [PMC3926022](https://pmc.ncbi.nlm.nih.gov/articles/PMC3926022/)). In step 4 every stimulus
  sits near a single matched level, so there is little range for contraction to act on. The
  residual order effect is mainly each participant's own TOE.
- **Balancing orders is the standard remedy.** Ulrich & Vorberg show that when order effects are
  present, pooled 2AFC percent-correct mis-states discrimination. They fit each presentation
  order separately, constrained so that the two orders average to 0.5 when the stimuli are equal
  (2009, *Atten Percept Psychophys* 71:1219–1227,
  [doi:10.3758/APP.71.6.1219](https://doi.org/10.3758/APP.71.6.1219); abstract and Europe PMC
  record only). The idea carries over directly. Under equality, a participant with a TOE
  picks *first* (or *second*) more often in both orders. So **order-consistent** answers
  (first/first, second/second) are what equality plus a bias predicts, and only
  **channel-consistent** answers (the same channel wins in both orders) are evidence of a real
  difference.
- **Sequential dependence between trials.** People update an internal reference trial by trial,
  so each response depends partly on the previous trials (Dyjas, Bausenhart & Ulrich 2012,
  *Atten Percept Psychophys* 74:1819–1841,
  [doi:10.3758/s13414-012-0362-4](https://doi.org/10.3758/s13414-012-0362-4); abstract only).
  Interleaving channels, rather than running one channel's trials back to back, keeps that
  dependence from lining up with a single channel.
- **MoA start-point bias.** The comparison document already settles that one adjustment depends
  on where it starts and which way it approaches, and that the fix is two adjustments, one
  starting below and one above, averaged (§7.3). That reasoning applies unchanged to a
  re-adjustment.

**What two trials can and cannot tell you (arithmetic, not literature).** Let *p* be the
probability of choosing the truly stronger stimulus on one trial (0.5 when the two are equal).
Assume no bias and no lapses. Under the 2AFC model, *p* = Φ(d′/√2).

| Rule: flag when the same channel wins in… | False alarm per channel (equal, no TOE) | …with a strong TOE (P(first) = 0.7) | Flag rate, *p* = 0.76 (d′ ≈ 1.0) | *p* = 0.90 (d′ ≈ 1.8) | *p* = 0.95 (d′ ≈ 2.3) | P(≥1 false flag per session, 4 channels) |
|---|---|---|---|---|---|---|
| both of 2 trials (1 pair) | 0.50 | 0.42 | 0.64 | 0.82 | 0.91 | 0.94 |
| all 4 trials (2 pairs) | 0.125 | 0.088 | 0.34 | 0.66 | 0.82 | 0.41 |
| all 6 trials (3 pairs) | 0.031 | 0.016 | 0.19 | 0.53 | 0.74 | 0.12 |

A flag from *k* pairs has probability 2·(¼)^k when the channels are equal and there is no TOE.
With a TOE, a pair is channel-consistent with probability 2·P(first)·(1−P(first)), so a
TOE makes false flags *less* likely under this rule.

What follows:

- **Two trials cannot tell "equal" from "different."** Under equality, channel-consistent and
  order-consistent pairs are equally likely (0.5 each). A rule that flags on one pair would
  re-adjust about half of all correctly matched channels, and some channel in 94 % of sessions.
  The spec's minimum of 8 comparisons can only be a first stage.
- **Ending early loses nothing.** Under the "all 4 the same channel" rule, a first pair that is
  order-consistent, or favours different channels in its two trials, has already decided the
  outcome: a pass. So the second pair is run only when the first is channel-consistent. False
  alarms and power are exactly those of the fixed 4-trial rule, and the expected number of
  trials under equality is 3, not 4.
- **This is a gross-error check, not a precision check.** No affordable trial count gives good
  power at 1 d′. The precision of the match comes from the averaged two-start MoA. The check
  exists to catch a match that is clearly off: a lapse, a misunderstood adjustment, a timed-out
  adjustment, a badly coupled actuator. The end-of-calibration evenness check (SPEC §9) is the
  second net, for the moving pattern.

**Time (with the comparison document's own figures: 12–15 s per comparison, 30–45 s per
adjustment; midpoints 13.5 s and 37.5 s).** The §7.2 budget has 8 comparisons, 1.6–2.0 min per
session. The expected cost per session of each option, including the re-check after a
re-adjustment, when all channels are in fact equal:

| Option | No TOE | Strong TOE | Worst case (every channel flags twice) |
|---|---|---|---|
| 1 pair, re-adjust with 2 MoA | ≈ 5.2 min | ≈ 4.7 min | ≈ 10.6 min |
| **2 pairs with early stop, re-adjust with 2 MoA (recommended)** | **≈ 3.7 min** | **≈ 3.2 min** | ≈ 12.2 min |
| 3 pairs with early stop, re-adjust with 2 MoA | ≈ 3.2 min | ≈ 3.0 min | ≈ 16 min |

The recommended rule costs about 1.2–2.1 min more per session than the §7.2 figure. That is
within the uncertainty the comparison document already flags against open item 8. The worst
case is a tail event with probability of order 10⁻⁷ when the channels are equal.

## Options

**A. Flag when the same channel wins in both orders (one pair).** Needs no extra trials. It is
the natural first reading of "mismatch." *Risk:* a 50 % false-alarm rate, so re-adjustment
becomes routine and most re-adjustments are triggered by noise. That costs time and fatigue,
and it trains the participant that the comparison is "testing" them. It does not bias the match,
because a re-adjustment is an independent new estimate, but it wastes about 3.4 min per session
for almost no information.

**B. Two pairs, early stop (recommended).** Run one pair. Stop and pass if it is
order-consistent. If it is channel-consistent, run a second pair. Flag only if the same channel
won all four. *Cost:* 3 trials per channel on average. *Risk:* 34–66 % power at d′ 1–1.8, so a
moderate residual mismatch can pass. That is acceptable for a gross-error check with the
evenness check behind it. A 12.5 % false-alarm rate per channel means about 4 sessions in 10 see
one unneeded re-adjustment, which costs time but not validity.

**C. Three pairs, early stop.** False alarms 3 % per channel. Cheaper on average than B when
the channels are equal. *Risk:* power at d′ 1.8 falls to 0.53, a real gross mismatch takes 6
trials to flag, and each lapse costs more power. It is a reasonable pilot setting if B turns
out to re-adjust too often.

**D. A fixed block of 4 trials per channel with a threshold below 4/4 (e.g. ≥ 3 of 4).**
*Risk:* a 62.5 % false-alarm rate when the channels are equal, worse than A. Rejected.

For re-adjustment itself:

- **One MoA trial.** Saves about 37 s per re-adjustment, or about 5 s per channel in
  expectation. *Risk:* brings back the start-point and approach bias that §7.3 exists to remove,
  in a known direction, and the underpowered 2AFC re-check cannot be relied on to catch it.
  Rejected.
- **Two MoA trials, from the same below and above start points as the original.** Matches the
  original procedure, gives a fresh estimate of the spread, and costs little.

For the loop:

- **Unlimited passes until the check passes.** Can loop on a systematic problem that more
  adjustment cannot fix: an actuator fault, a production/discrimination dissociation
  (Teghtsoonian & Teghtsoonian, cited in §7.3), or site-specific adaptation. Worst-case time is
  unbounded. Rejected.
- **One re-adjustment pass, then continue with a warning.** When the channels are equal, the
  chance of two false flags in a row is about 1.6 % per channel (0.125²). A second flag is
  therefore strong evidence of a systematic cause, which is for the experimenter and the
  evenness check to deal with rather than more loops.

## Recommendation

**Option B, with one two-start re-adjustment pass and a single re-check.** In concrete terms,
with every number in `config/` and pilot-tunable:

1. **Mismatch definition.** A test channel is *flagged* only if the **same channel is judged
   stronger in every trial of `equalise.pairs_to_flag = 2` consecutive order-balanced pairs**
   (4 of 4). Any order-consistent answer (first/first, second/second), and any pair whose two
   trials favour different channels, is a **pass** and stops that channel's check. The rationale
   for the code comment: under equality with a time-order bias, order-consistent answers are
   what is expected, so only order-independent preference counts as evidence.
2. **Order of trials.** Stage 1: all four channels' first pairs (8 trials) in randomised,
   interleaved order, with each channel getting one `test_first` and one `reference_first`. Stage
   2: second pairs for channel-consistent channels only, also interleaved. Keep the gap between
   the two stimuli of a trial fixed across all trials, so that each participant's TOE stays
   constant and cancels across the two orders.
3. **Re-adjustment.** For each flagged channel, run **two MoA trials from the original below and
   above start points** (never starting from the rejected match). The mean of the two
   **replaces** the flagged match, and the channel's derived anchor set is recomputed from it.
   The original settings are kept in the data, so an analysis can average all four settings
   instead if it prefers.
4. **Re-check and cap.** Re-run the same check (steps 1–2) on re-adjusted channels only. The
   reference has not changed, so passed channels need no re-check. **`equalise.readjust_max_passes
   = 1`.** If a channel flags again, continue with the re-adjusted match, set a per-channel
   `equalisation_unresolved` flag in the data, and show a warning naming the channel on the
   experimenter screen. The channel number and the mismatch say nothing about condition, so
   this is compatible with §16.
5. **Pilot tuning.** If pilot sessions re-adjust in more than about a third of sessions, or
   participants find the extra trials tiresome, set `pairs_to_flag = 3` (6/6: 3 % false alarms
   per channel, lower power). If flags frequently persist after re-adjustment, look at the
   hardware or at transfer from the 3 s hold (comparison doc §7.4) rather than raising
   `readjust_max_passes`.

For the schema (the main session's decision): each `touchcal_compare` row needs to say which
pass it belongs to (0 = original match, 1 = after re-adjustment) and which pair it is (1 or 2),
so the rule can be re-scored offline. The existing `readjusted` bool alone cannot reconstruct
the sequence. Separately, `docs/DATA_SCHEMA.md` still says this table includes catch trials,
while SPEC §9 moved the zero-pressure catch trials into the step 2 estimation run. The two are
out of step.

Why B: it is the smallest rule that separates order-independent preference from what a
time-order bias produces under equality at a false-alarm rate a session can absorb. It costs
about 1.2–2.1 min more than the §7.2 figure on average. It is cheaper than option A, because A
re-adjusts half of all correct matches. And B and C differ in one config value, so the pilot
can choose between them.

**Confidence is medium.** The arithmetic is exact under its assumptions. The literature firmly
supports (a) prevalent, sign-varying order effects and (b) balancing orders so that they cancel.
No source addresses this exact check. The tactile-specific TOE evidence is one preprint plus a
vibration study. Several primary papers could be read only as abstracts. Choosing 2 pairs over
3 is a judgement trading false alarms against power and time.

## What would change this

- **Pilot re-adjustment rate well above 12.5 % per channel** with re-adjusted matches close to
  the originals: false alarms (or a sequential artefact) are dominating. Move to
  `pairs_to_flag = 3`.
- **Re-adjusted matches that differ from the originals by more than the two-start spread** in
  flagged channels: the check is catching real errors. B is working, and it may be worth
  lowering the false-alarm threshold further.
- **Frequent `equalisation_unresolved`, or evenness-check failures in channels that passed
  step 4:** the 3 s static match does not transfer, or the gain model fails (the scheme B pilot
  condition in comparison doc §7.2). The fix is the pulse-at-pattern-timing option in §7.4, not
  this rule.
- **A pressure-on-skin TOE study showing large, consistent-sign bias** (P(first) far from 0.5)
  would not change the rule, since bias lowers false alarms. But it would lower power, and could
  justify 3 pairs.
- **Reinstating an "equal" response** would allow a ternary analysis (García-Pérez &
  Alcalá-Quintana). S dropped it on 26 Aug 2026, so it is noted here, not proposed.
