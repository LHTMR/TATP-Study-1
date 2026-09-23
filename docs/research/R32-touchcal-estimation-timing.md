# R32 — Touch-calibration estimation run: hold before the VAS, stimulus during rating, off-interval, amplitude spacing, catch-trial count

**Asked:** 2026-09-23. **For:** `docs/SPEC.md` §9 step 2 (Protocol B estimation run), acceleration-push stream C. **Confidence:** medium overall. By point: (1) medium, (2) medium, (3) **low**, (4) medium–high, (5) high.

Research was cut short at the integrator's request. Several key sources could be read only as abstracts or secondary summaries. They are marked as such below and listed under "To fetch".

## The question

SPEC §9 step 2 fixes the design: ten amplitudes across the participant's own [P10, P90] adjustment bracket on channel 3, in randomised order, with zero-pressure catch trials embedded (`catch_trial_fraction: 0.2`), one touch-intensity VAS per presentation, and a fit of `rating ~ a + b·log10(pressure)` that is inverted for P20, P30 and P80. The design itself is settled (`docs/calibration_methods_comparison.md` §7.1) and is not re-opened here. The spec does not give five presentation parameters:

1. how long the static pressure is on before the VAS appears;
2. whether the stimulus stays on during the rating, or is removed first;
3. the interval from stimulus off to the next warning cue;
4. whether the ten amplitudes are spaced evenly in log pressure or in linear pressure;
5. whether the catch trials are added to the ten amplitudes or replace some of them.

All five affect what is measured. Blinding is unaffected, because the run is identical in every condition (see the comment in `config/study1.yaml` under `fit_preview`).

## What the evidence says

**Static pressure and adaptation.**
- A sustained indentation on skin is felt only while the tissue is still moving. As the tissue stops yielding, the sensation fades ("pressure adaptation"), over seconds to tens of seconds depending on force and area. Sources: Nafe & Wagoner (1941), *J Gen Psychol* 25, "The nature of pressure adaptation", read only as a secondary summary; Zigler (1932), *Am J Psychol* 44:709–720, "Pressure adaptation-time: a function of intensity and extensity", citation only, found via Carmon & Finger (1971), [doi:10.2466/pms.1971.32.2.427](https://doi.org/10.2466/pms.1971.32.2.427). **Consequence:** for a static stimulus, the rated intensity depends on how long the stimulus has been on when the rating is given. The on-time must therefore be fixed, or at least logged.
- Slowly adapting afferents keep signalling a static indentation, while rapidly adapting ones signal mainly its onset. The comparison document's own reasoning (§7.4) is that a 3 s hold "clear[s] the inflation transient" and engages both. This matches standard receptor physiology; see the review by Frontiers in Human Neuroscience (2022) on SA/RA contributions, [doi:10.3389/fnhum.2022.862344](https://doi.org/10.3389/fnhum.2022.862344).
- For static indentation, magnitude-estimation functions follow a power law with a group exponent of about 1.0. Individual exponents range from 0.36 to 2.09, and neural and perceptual functions do not correlate across subjects. Source: Knibestöl & Vallbo (1980), *J Physiol*, [doi:10.1113/jphysiol.1980.sp013160](https://doi.org/10.1113/jphysiol.1980.sp013160). **Abstract only.** The stimulus duration used ("invariant", rectangular) could not be read.
- CT afferents respond to sustained indentation with a few seconds of adaptation, then about 20 s of low activity, then a "delayed acceleration" of firing. Löken et al. (2022), *J Neurophysiol*, [doi:10.1152/jn.00310.2021](https://doi.org/10.1152/jn.00310.2021) ([PMC9190740](https://pmc.ncbi.nlm.nih.gov/articles/PMC9190740/)), report it for a 45 mN monofilament and say it has no clear perceptual correlate. Vallbo et al. (1999), *J Neurophysiol*, [doi:10.1152/jn.1999.81.6.2753](https://doi.org/10.1152/jn.1999.81.6.2753), first described it (**abstract only**). **Consequence:** keeping each static presentation well under about 20 s keeps the stimulus clear of this regime.

**Repetition and fatigue.**
- CT afferents fatigue with repeated stimulation. Microneurography studies use a **30 s** interstimulus interval "to allow for recovery": Ackerley et al. (2014), *J Neurosci*, [doi:10.1523/JNEUROSCI.2847-13.2014](https://doi.org/10.1523/JNEUROSCI.2847-13.2014) ([PMC3931502](https://pmc.ncbi.nlm.nih.gov/articles/PMC3931502/)); Löken et al. (2022), as above. That interval protects **single-unit** firing, and it is set for stroking, which is the CT-optimal stimulus. It is not a perceptual requirement, and a static pneumatic press is not a CT-optimal stimulus.
- Perceptually, repeated CT-optimal brushing lowers pleasantness only slowly. Triscoli, Ackerley & Sailer (2014), *PLoS One*, [doi:10.1371/journal.pone.0113425](https://doi.org/10.1371/journal.pone.0113425) ([PMC4236195](https://pmc.ncbi.nlm.nih.gov/articles/PMC4236195/)), ran 120 trials over about 50 min with "5 s to complete both VAS" after each stroke. The pleasantness decline at 3 cm/s was "small, but significant" (β = −0.09) in the mixed-velocity experiment. Twelve static presentations are far below that exposure.
- Short gaps between repeated pressures produce summation. In cuff algometry, **1–2 s on / 1 s off** is the paradigm used to *induce* temporal summation: Graven-Nielsen et al. (2015), *Pain*, [doi:10.1097/j.pain.0000000000000294](https://doi.org/10.1097/j.pain.0000000000000294) (abstract, plus secondary descriptions of the paradigm); Polianskis et al. (2001), *Eur J Pain*, [doi:10.1053/eujp.2001.0245](https://doi.org/10.1053/eujp.2001.0245) (abstract). A calibration run must stay well clear of that regime.
- The pinprick protocol in this study already uses an ISI of 13–17 s (`config/study1.yaml`, from Scheuren et al. 2023). No touch-intensity estimation protocol with a stated recovery interval for static pneumatic pressure was found.

**Sequential effects.** In absolute judgement, the current response assimilates toward the previous stimulus and contrasts with stimuli further back. Longer intervals increase contrast. Source: Matthews & Stewart (2009), *Q J Exp Psychol*, [doi:10.1080/17470210802649285](https://doi.org/10.1080/17470210802649285) (abstract). Randomised order, which the spec already requires, turns these effects into noise rather than bias. They are not eliminated, so the previous amplitude is worth logging.

**Concurrent versus retrospective ratings.** Ratings given after a stimulus has ended are distorted relative to concurrent ones, and discriminative information is partly lost. Source: Khoshnejad et al. (2014), *Pain*, [doi:10.1016/j.pain.2013.12.015](https://doi.org/10.1016/j.pain.2013.12.015), a heat-pain study with a 14 s delay (**abstract only**).

**Spacing of amplitudes.** The DFNS stimulus–response test for pinprick uses a **geometric series**, doubling from 8 to 512 mN. It is applied in balanced order five times each, and the analysis works on log-transformed values (Rolke et al. 2006, *Pain*, [doi:10.1016/j.pain.2006.01.041](https://doi.org/10.1016/j.pain.2006.01.041); **closed access**, per Unpaywall, and the protocol details come from secondary descriptions). Pneumatic-actuator studies also sample pressure over wide ratios, for example 4–30 kPa in the *IEEE Trans Haptics* pneumatic intensity work ([doi:10.1109/TOH.2024.3399394](https://doi.org/10.1109/TOH.2024.3399394), abstract only). The general design principle is not a literature claim but a property of least squares: a regression slope is estimated best, and its predictions are most uniform, when the design points are spread evenly in the **predictor** actually fitted. Here the predictor is log10(pressure).

**Catch trials.** SPEC §9 cites Berquin et al. (2010) for the "flag if more than 20 % felt" rule. Nothing found fixes the number of catch trials in a short estimation run.

## Options

**(1) Hold before the VAS appears**
- **a. 3.0 s, counted from the pressure command.** This is consistent with `comparison_hold_s` and the §7.4 rationale. The risk is that inflation time is unknown (SPEC §20 item 3), so at high amplitudes part of the 3 s may still be rise time.
- b. 3.0 s from "pressure reached", if the controller reports it. This is better, but it depends on a controller protocol that is not yet known (§20 item 2).
- c. Longer, 5–10 s. This deepens adaptation and lengthens the run for no gain in the fit.

**(2) Stimulus during the rating**
- **a. Stimulus stays on until confirm, with a cap.** This matches the approved present-tense question ("How intense is the **current** touch…", "just nu"). It also matches step 1, where the adjustments are made with the stimulus on, so the production–estimation gap that step 2 measures is not confounded with a change in stimulus state. It matches the intervention touch-rating blocks too. The cost is that on-time at confirm varies with rating time, so adaptation varies. This is mitigated by the cap and by logging the on-time.
- b. Remove the stimulus, then show the VAS. On-time is fixed exactly. But the rating becomes retrospective, which is the distortion Khoshnejad et al. describe. It also contradicts the present-tense wording, and changing that wording belongs to the main session and the ethics documents, not to this report.
- c. Remove the stimulus at a fixed time while the VAS is still up. This combines both costs and asks about a "current" touch that has gone.

**(3) Off-interval, stimulus off to the next warning cue**
- a. 30 s, the CT microneurography convention. About 12 × 39 s ≈ 8 min per session. That is expensive against the scheme B budget of 10.6–14.5 min for the whole calibration, and it protects single-unit firing that this run does not measure.
- **b. Jittered 8–12 s (uniform).** About 12 × ~19 s ≈ 4 min. This is well clear of the 1 s summation regime, and it is comparable to the pinprick ISI already in use. The jitter stops the participant anticipating onset, although the warning cue already signals it. The risk is residual carryover. That carryover is randomised by the design and can be checked from the logged previous amplitude.
- c. 3–5 s. This is cheap, but it is close to summation paradigms, and it leaves little time for deflation and skin recovery.

**(4) Spacing**
- **a. Ten amplitudes evenly spaced in log10(pressure) from the P10 adjustment to the P90 adjustment inclusive.** This matches the fitted form and the DFNS geometric-series practice. It puts more points at the low end, where pneumatic pressure-to-indentation behaviour is least linear.
- b. Linear spacing. This suits a linear fit (`estimation_fit: linear_pressure`). Under the log fit it leaves the low end under-sampled.
- Note: for a narrow bracket (P90/P10 ≈ 3–4) the two schemes differ very little. The choice matters when P10 sits close to threshold and the ratio is large. Either way the lower bracket end must be greater than 0 kPa, or log spacing is undefined. At the low end, log-spaced steps may be finer than the valve resolution, which is unknown (§20 item 2).

**(5) Catch trials**
- **a. Added.** Ten amplitudes plus `round(catch_trial_fraction × n_amplitudes)` = **2** catch trials, 12 presentations in all. The fit keeps all ten points, and the fit is the per-participant quality gate.
- b. Replace two amplitudes. This leaves 8 fit points, weakens the quality gate and saves only about 40 s.
- Note the granularity problem under either option. With 2 catch trials, "more than 20 % felt" means **any** felt catch trial raises the flag (1 of 2 = 50 %). Berquin's 20 % rule assumed many catch trials. Also, what counts as "felt" on a VAS is not defined anywhere found. It needs a stated rule, for example a rating at or above the 10 % "just noticeable" anchor, recorded as an **[R]** decision.

## Recommendation

All values go in config and are pilot-tunable. Suggested keys are in brackets.

1. **Hold 3.0 s from the pressure command before the VAS appears** [`estimation_hold_s: 3.0`]. If the controller later reports "pressure reached", count from that instead. Log the commanded pressure and the VAS onset time. This reuses the settled §7.4 rationale rather than introducing a second number.
2. **Keep the stimulus on through the rating until confirm**, with a **rating timeout of 12 s after VAS onset** [`estimation_rating_timeout_s: 12.0`]. The timeout keeps the total static on-time at 15 s or less, clear of the ~20 s CT delayed-acceleration regime and of long adaptation. On timeout, deflate, record the trial as timed out, and re-present that amplitude once at the end of the run. Log the stimulus on-duration at confirm, so adaptation can be used as a covariate. The main reason for this choice is the present-tense approved wording, together with consistency with step 1. It is not a literature finding.
3. **Off-interval jittered uniformly over 8–12 s**, from the deflate command to the next warning cue [`estimation_off_min_s: 8.0`, `estimation_off_max_s: 12.0`]. The existing `warning_lead_s` of 1.0 s then precedes onset. Log the previous trial's amplitude on each row.
4. **Log-even spacing: ten values, inclusive of both adjusted bracket ends** [`estimation_spacing: log`]. The upper end is not extended beyond the participant's own "just uncomfortable" setting. Assert that the lower end is greater than 0 kPa.
5. **Catch trials are added: 10 + 2 = 12 presentations.** They are excluded from the fit. Constrain the randomisation so the first presentation is not a catch trial and no two catch trials are adjacent. That way the first rating is anchored by a real touch, and an absence is never followed by another absence. Record that, at n = 2, the 20 % flag is equivalent to "any felt".

Estimated run length is 12 × (1 s cue + 3 s hold + about 4 s rating + about 10 s off) ≈ **3.6 min**.

## What would change this

- **Pilot on-time at confirm.** If median rating time is well above 5 s, or ratings fall with on-time within participant, the adaptation confound under 2a is real. Then move to a shorter timeout, or to 2b with the wording revised through the ethics route.
- **Pilot carryover.** If the residuals of the fit correlate with the previous amplitude, lengthen the off-interval toward 15–20 s.
- **Inflation rise time (§20 item 3).** If reaching the upper-bracket pressure takes more than about 1 s, count the hold from "pressure reached", not from the command.
- **A narrow bracket in practice (P90/P10 < 3).** The spacing choice is then immaterial.
- **Catch trials.** If catch trials are felt often, or the flag fires in most sessions, reconsider the count (3–4) or the "felt" threshold.
- **Full texts.** Knibestöl & Vallbo (1980) for the stimulus duration used in static magnitude estimation. Case et al. (2021, [PMC7865002](https://europepmc.org/articles/PMC7865002)) for the timing of ratings in the pneumatic oscillating-compression-sleeve protocol, which is the closest analogue to this garment but could not be fetched this session.

## For S, not decided here

- **Maximum static on-time.** The 15 s total is a comfort- and safety-adjacent duration at up to "just uncomfortable" pressure. It is offered as pilot-tunable, not as a settled limit.
- **No wording is proposed.** Option 2b would need the present-tense question reworded, which goes through the ethics documents.
- **Blinding is unaffected.** The run is identical in every condition.
