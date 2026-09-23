# R30 — What numbers define a "flat", "non-monotonic" or "poor residuals" stage-1 touch-calibration fit?

**Asked:** 2026-09-23. **For:** `docs/SPEC.md` §9 step 2 (Protocol B estimation run), stream C.
**Confidence:** low for the numeric values, medium for which statistic each criterion uses.

## The question

Protocol B step 2 collects about ten intensity-VAS ratings (0–100) at pressures spread across a
bracket the participant set by adjusting to 10 % ("just noticeable") and 90 % ("just
uncomfortable"). It fits `rating ~ a + b·log10(pressure)` by OLS, rating on pressure, and
inverts the fit for P20, P30 and P80. `docs/SPEC.md` §9 says stage 1 fails when the fit is
"flat, non-monotonic, or has poor residuals", and that the failure must be caught before stage 2.
The spec gives no numbers, and it does not say which statistic each word means.
`docs/DATA_SCHEMA.md` `touchcal_fit` already stores `slope`, `r_squared`, `residual_sd`,
`bracket_min_kpa` and `bracket_max_kpa`, a `monotonic` boolean (currently "fitted slope is not
positive") and `stage1_pass`.

The design itself is settled (`docs/calibration_methods_comparison.md` §7.1) and is not
re-opened here. Only the three thresholds are in question.

## What the evidence says

**1. No published touch or pneumatic-pressure calibration has a fit-quality gate I could find.**
The closest precedents are heat-pain calibrations that fit a regression to 24 trials:

- **Atlas et al. (2010)** required "reliable relationships between stimulus temperature and
  reported pain (minimum R² ≥ 0.40)" after 24 pseudorandom trials, plus tolerance within
  42–48 °C. [PMC2966558](https://pmc.ncbi.nlm.nih.gov/articles/PMC2966558/),
  doi:[10.1523/JNEUROSCI.0057-10.2010](https://doi.org/10.1523/JNEUROSCI.0057-10.2010).
  This is the earliest source of the R² ≥ .4 rule that I found.
- **Amir et al. (2022)**, from the same lab, excluded participants whose "ratings were not
  ordinally consistent with temperature or [who] had an r² value of less than .4 (based on
  calculation without outliers; n = 16 ineligible; 4.7 % of participants screened)". They also
  excluded a threshold below 36 °C, a tolerance above 50 °C, and "a difference of less than 4 °C
  between threshold and tolerance". They do not define "ordinally consistent" numerically. r²
  had ICC .171 across visits, and they conclude: "it may not be appropriate to use
  goodness-of-fit to determine eligibility". Participants with r² > .8 agreed closely between
  visits, and the unreliability sat in those with weaker fits. 0–10 VAS, 24 trials.
  [PMC9644806](https://europepmc.org/articles/PMC9644806),
  doi:[10.1016/j.jpain.2022.01.011](https://doi.org/10.1016/j.jpain.2022.01.011).
- **Świder et al. (2024)** used R² both to truncate the regression series and as a rejection
  criterion, together with convergence of the regression gradient
  ([abstract](https://pubmed.ncbi.nlm.nih.gov/38229548/),
  doi:[10.1111/psyp.14505](https://doi.org/10.1111/psyp.14505)). The comparison document gives
  their cut-off as R² < 0.4. **I could read only the abstract.** The medRxiv preprint PDF
  (doi:[10.1101/2022.10.03.22280662](https://doi.org/10.1101/2022.10.03.22280662)) could not be
  extracted, so I could not confirm the exact rejection rules. The paper is listed under To fetch.
- **Badzińska et al. (2025)**, a systematic review of 51 electrical-pain calibration studies,
  found that "69 % of studies did not verify the effectiveness of their calibration processes".
  There is no field convention to adopt.
  [PMC12363490](https://europepmc.org/articles/PMC12363490),
  doi:[10.1097/j.pain.0000000000003588](https://doi.org/10.1097/j.pain.0000000000003588).
- **DFNS QST** summarises its pinprick stimulus–response function (MPS, seven forces × 5,
  0–100 NRS) as the geometric mean of the ratings and applies no fit-quality criterion (Rolke et
  al. 2006, doi:[10.1016/j.pain.2006.01.041](https://doi.org/10.1016/j.pain.2006.01.041). I took
  this from secondary summaries, not the full text, and the paper is listed under To fetch.) QST
  offers no precedent here.

**2. How noisy single ratings are.** Quiton & Greenspan (2008) repeated two individually
calibrated heat levels (targets 40 and 70 on a 0–100 VAS). Within-session CV of intensity ratings
was 0.42 (SD 0.4) at the lower level and 0.14 (SD 0.1) at the higher. That is roughly 15–17 VAS
points at mid-scale and about 10 near the top, with a long right tail across people. Variability
was "a characteristic of individual subjects over both short and long time scales".
[PMC5105332](https://pmc.ncbi.nlm.nih.gov/articles/PMC5105332/),
doi:[10.1016/j.pain.2007.08.034](https://doi.org/10.1016/j.pain.2007.08.034). So a noisy fit
reflects the person more than the run, and **re-running a noise failure will often fail
again**. The comparison document's simulation assumes σ = 10 for a typical reporter and σ = 18
for a noisy one (§5.1). These are heat-pain figures, and no equivalent exists for pneumatic
touch intensity.

**3. What this design implies (my derivation, not a source).** The derivation assumes ten
amplitudes evenly spaced in log10 pressure, including both ends of a bracket of width
W = log10(P_max/P_min). That is the spacing [R32](R32-touchcal-estimation-timing.md)
recommends. Linear spacing would change the constants a little.

- Σ(x − x̄)² = 1.02 W², so SE(b) ≈ σ/(1.01 W).
- Define the **fitted span** S = b·W. This is the fitted rating at the top of the bracket minus
  the fitted rating at the bottom. Its SE ≈ σ, **whatever the bracket width**, and the slope
  t-statistic ≈ 1.01·S/σ.
- Expected R² ≈ 0.113 S² / (0.113 S² + σ²). R² therefore mixes flatness with noise.
  - At S = 80: σ = 10 gives R² ≈ .88, σ = 18 gives .69, σ = 25 gives .54.
  - At S = 60, σ = 25 gives R² ≈ .40.
- **The slope b cannot be compared across participants.** Take two participants who both use
  the scale fully. One with a wide bracket (W = 1.0, a tenfold pressure range) has b ≈ 80, and
  one with a narrow bracket (W = 0.3) has b ≈ 270. A floor on b would fail the first person
  for having a wide dynamic range. S does not depend on W.
- **Expected S is below 80.** The bracket comes from magnitude production and the ratings from
  magnitude estimation. The regression effect (Teghtsoonian & Teghtsoonian 1978, cited in
  `docs/SPEC.md` §9) compresses whichever variable the participant controls. The produced
  10 %–90 % bracket is therefore likely narrower than the estimated one, and ratings across it
  will span less than 80 points. How much less, for this stimulus, is unknown. A floor at
  VAS 10 adds a little more compression.
- The critical Spearman ρ for n = 10 is 0.648 two-sided at α = .05
  ([MetricGate table](https://metricgate.com/docs/spearman-critical-values/)). The one-sided
  value is ≈ 0.56 (0.549 by the t-approximation; exact tables give 0.564, which is Σd² ≤ 72 when
  there are no ties). At n = 10 with no ties, "ρ ≥ 0.56" and "ρ ≥ 0.564" accept exactly the same
  rank orders.

## Options

**Flat**

- *(a) Minimum slope b (VAS/log10).* This fails participants with wide brackets and passes
  shallow fits on narrow ones. It is invalid when the bracket is set per participant. **Reject.**
- *(b) Minimum fitted span S (VAS points across the sampled bracket).* It can be read directly
  in scale units ("ratings rose by at least N points from the bottom to the top of the
  participant's own bracket"), it is independent of W, and it can be computed from the columns
  already stored. Risk: the estimate has SE ≈ σ, so a noisy reporter near the floor can fail by
  chance.
- *(c) Slope significance test.* This asks whether there is any relationship at all, not
  whether the relationship is usable. A very precise participant with a 15-point span passes it,
  even though their window would be meaningless. It is useful only as a lower bound, and the ρ
  floor below already provides one.

**Non-monotonic**

- *(a) b ≤ 0 only.* The span floor already implies b > 0, so this adds nothing.
- *(b) Spearman ρ floor on ratings against pressure (catch trials excluded).* This is Amir's
  "ordinal consistency", which the comparison document picked out as "cheap, assumption-free,
  and the robust half of their eligibility screen". It does not depend on the log fit being the
  right shape, and a single extreme point cannot manufacture it. At the one-sided 5 % critical
  value, it is also the nonparametric version of the slope test in flat (c). Risk: with only
  n = 10 it has little power, so it is the criterion most likely to fail noisy reporters (below).

**Poor residuals**

- *(a) R² floor (≥ 0.4).* This is the literature's rule, but R² double-counts flatness because
  it depends on S. Its own originators advise against gating on it (ICC .171). **Store it, do
  not gate on it.**
- *(b) Residual-SD ceiling (VAS points, n − 2 denominator).* Measures scatter directly, in the
  units that move the inverted targets. It is independent of span, so the three criteria stay
  separable when tuning. A ceiling of 25 matches R² = .40 at S ≈ 60, the span this design is
  likely to produce, so it roughly corresponds to the Atlas/Amir rule, which excluded about 5 %
  of participants when combined with the ordinal check.

**Approximate single-run failure rates** for the recommended values below. These are my
analytic approximations (a normal for S, χ²₈ for residual SD, Fisher-z for ρ), not a
simulation, and they are optimistic in the same ways the comparison document's simulation is:

| True S, σ | span < 40 | ρ < 0.56 | resid SD > 25 |
|---|---|---|---|
| 80, 10 | ≈ 0 | ≈ 0.4 % | ≈ 0 |
| 60, 10 | ≈ 2 % | ≈ 2 % | ≈ 0 |
| 80, 18 | ≈ 1 % | ≈ 9 % | ≈ 5 % |
| 60, 18 | ≈ 13 % | ≈ 23 % | ≈ 5 % |

The criteria overlap heavily, so these rates do not add. Noise mostly shows up in ρ. The
residual-SD ceiling mainly catches misfit where the rank order is good but the log-linear shape
is not, for example a step-like or saturating function, or a single wild rating.

## Recommendation

Three independent criteria, each a config value that can be tuned during piloting. The fit and
all three statistics use the non-catch trials only. Stage 1 fails if any criterion fails:

| Criterion | Statistic | Suggested config key | Value |
|---|---|---|---|
| Flat | fitted span S = b·log10(bracket_max/bracket_min), VAS points | `stage1_min_fitted_span_vas` | **40.0** (half the nominal 80-point bracket) |
| Non-monotonic | Spearman ρ, ratings vs pressure | `stage1_min_spearman_rho` | **0.56** (one-sided 5 % critical value at n = 10) |
| Poor residuals | OLS residual SD, n − 2 denominator, VAS points | `stage1_max_residual_sd_vas` | **25.0** (≈ R² .40 at S ≈ 60) |

Why these:

- **Span, not slope.** It is the only flatness measure that means the same thing when brackets
  differ.
- **ρ, not the slope's sign.** It is the assumption-free check Amir used, it makes a separate
  slope test unnecessary, and a slope that is not positive can never pass the span floor anyway.
- **Residual SD, not R².** R² would count flatness twice and is advised against by the lab that
  introduced it.
- **All three are deliberately lenient.** The gate should catch runs that are clearly broken,
  not certify precision, because Quiton & Greenspan show that noise is largely a trait. The
  diagnostics are stored so that precision can be handled at analysis.
- **R² stays stored and reported but not gated**, so results remain comparable with Atlas and
  Amir.

Three notes for the main session. These are implementation observations, not decisions:

- The `monotonic` column in `docs/DATA_SCHEMA.md` is currently defined as "slope > 0". Under this
  recommendation it should mean ρ ≥ the floor, or a `spearman_rho` column should be added
  beside it.
- Storing `fitted_span_vas` and `spearman_rho`, and ideally one boolean per criterion, lets the
  pilot re-tune from the data without re-deriving anything.
- The ρ floor depends on n. If `estimation_n_amplitudes` changes, or trials can go unrated, the
  floor has to be revised (n = 9 needs about 0.60, and n = 12 about 0.50) or stated as an α.

## What would change this

- **Pilot failure rates per criterion.** If ρ is the sole reason for failure in more than about
  10 % of runs while span and residual SD pass, lower the ρ floor to about 0.45 (the one-sided
  10 % value). The run's rank order is then noisy but its fit is usable. If span fails often,
  the regression effect is compressing the ratings more than assumed. That points to the
  bracket procedure (step 1), not to the floor.
- **Observed residual SDs for pneumatic touch intensity.** If typical pilot values are below
  about 10, a ceiling of 20 would be defensible. If they are around 20, 25 is already tight.
- **Test–retest across the three sessions.** If S or residual SD is as unreliable across
  sessions as Amir's r², it should not gate at all, only flag.
- **The full text of Świder et al. (2024).** If its gradient-convergence rule turns out to be a
  span or slope criterion with a stated value, that value is a better anchor than "half the
  bracket".
- **What happens on failure.** This is not settled in `docs/SPEC.md` §9 and is outside this
  question. If failure excludes the session rather than prompting a re-run, all three values
  should be loosened further.
