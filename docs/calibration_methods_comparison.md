# Choosing the calibration procedures — pinprick (§1–6) and touch pressure (§7)

Rev. 8, 22 Aug 2026. Rev. 4 rewrote this as a single coherent argument, superseding revs 1–3;
rev. 5 added full definitions of the simulation variables; rev. 6 corrects the informed-prior
figures and records the decision in §6; rev. 7 rewrote §7 around the proposed method-of-adjustment
design for Protocol B, with a time budget; rev. 8 records the Protocol B decisions (scheme B,
channel 3 as reference, accelerating control).
Companion file: `calibration_sim.py` (reproduces every number in §5).

---

## 1. The question

**Estimate F₄₀, the monofilament force at which the participant's median pain VAS rating is 40 %,
using as few painful applications as possible.** Run three times per session (pre-S, post-S,
post-I), three sessions per participant.

Two outputs are needed, and they have different requirements:

- **A filament to use.** Post-S's output is the fixed force for all six intervention short
  protocols, and hence for the primary outcome. This is a discrete choice among ~7 filaments;
  what matters is picking the right one.
- **F₄₀ in mN as a dependent variable** (Table 1, at all three time points). This is continuous
  and needs interpolation between filaments.

This is *not* the same objective as characterising the whole stimulus–response function. That
distinction matters for how the literature applies — see §4.3.

---

## 2. The hardware constraint

Aesthesio (DanMic) Semmes–Weinstein, the same set as Ng et al. (2024). Within the 100–3000 mN
range there are **seven filaments**: 98, 147, 255, 588, 980, 1760, 2940 mN (nominal 100, 150, 260,
600, 1000, 1800, 3000). The 260 mN filament of §3.6.1 is the 5.46, actual force 255 mN. The kit
continues below 100 mN (78.4, 58.8, 39.2, 19.6 …) and the ladder in config should list whatever is
actually held.

Mean step 0.246 log₁₀ (factor 1.76), unequal — the 255→588 gap is a factor of 2.31.

**The ladder is already about as fine as discrimination allows.** Ng et al. measured a Weber
fraction of 0.88 for noxious mechanical discrimination on the hand dorsum, so one JND is
log₁₀(1.88) = 0.274 log₁₀ and the mean filament step is **0.90 JND**. No procedure can resolve
better than roughly one step, and no finer hardware would help much.

Scale of the shift to be tracked: Scheuren et al. found the NRS-4 force fell from 499 to 109 mN
after sensitisation — 0.662 log₁₀, **2.7 steps of this ladder**.

---

## 3. Decomposing the problem

Every candidate procedure is some combination of three separable jobs. Treating them separately is
what makes the trade-offs legible.

| Phase | Job | Options |
|---|---|---|
| **Search** | Find which 2–3 filaments bracket F₄₀ | Ascend from below; descend from above; start from a prior and step; bisect |
| **Measure** | Collect enough ratings near the bracket | Repeats at the bracketing filaments, pseudorandom order; or keep stepping adaptively |
| **Estimate** | Convert ratings to F₄₀ | Fit rating on log₁₀ force; average staircase reversals in log units |

Two consequences fall out immediately.

**Ascending is the pain-minimal search.** By construction it approaches from below and stops as
soon as it crosses 40 %, so it never delivers a stimulus much above target. Its known cost —
predictability inflating expectation (Badzińska) and anticipation (Cornsweet) — is paid on search
trials. If the *measurement* phase is pseudorandom, those search trials need not enter the estimate
at all, so the cost is largely avoided. That is the argument for the ascend-then-pseudorandom
hybrid, and the simulation supports it.

**The search start is a free parameter that nobody in the literature exploits**, because no
published study repeats a calibration within a session. You always have a prior: post-S has pre-S
from 40 minutes earlier plus Scheuren's expected 2.7-step drop; post-I has post-S; sessions 2 and 3
have session 1. Starting the ascent from an informed prior instead of the bottom of the kit saves
~3.5 applications with no loss of accuracy (§5). It also introduces a bias risk toward the prior,
so the ascent must still be allowed to run in either direction and the start value must be logged.

---

## 4. What the literature actually offers

### 4.1 The classic adaptive-procedure papers do not cover this case

Cornsweet (1962), Levitt (1971), Treutwein (1995), García-Pérez (1998, 2002), Leek (2001) are all
restricted to **binary responses** and all assume a **freely adjustable stimulus continuum**.
Treutwein states both restrictions explicitly (p. 2504). Their convergence guarantees and their
bias/SE figures do not transfer to a VAS target on a fixed 7-level ladder.

Binarising the VAS at 40 does make them applicable, and 1-up/1-down then converges on median
rating = 40, which is the right target. The cost is information: a rating of 41 and a rating of 95
both score "yes" and both move one step. Also, at a 12–16 application budget you get 4–6 reversals,
against García-Pérez's recommended minimum of 8 and his warning not to use 1-up/1-down below 20.

### 4.2 Rating-guided jumps are supported — by stochastic approximation

Stepping in proportion to the discrepancy between rating and target is the **Robbins–Monro process**
(1951), x_{n+1} = x_n − (c/n)(z_n − φ). Nothing requires z_n to be binary. Treutwein covers it
(p. 2508–9): converges to any target with probability 1, requiring only monotonicity; and argues
(p. 2520) these methods are less susceptible to parameter mismatch than parametric ones.

**Kesten (1958) accelerated stochastic approximation** is the version that matches the intent:
x_{n+1} = x_n − [c/(2 + m_shift)](z_n − φ), where the step shrinks only on reversals. Large jumps
while far away, fine steps once bracketing, convergence still proven and faster than plain RM.

### 4.3 The two pain-calibration papers, and why Amir's objective differs

**Świder et al. (2024)** compare a binarising method against regression on the same data. Their TM
method takes ratings as crossing events (first current rated 1; the current just before the first 0
on the descending run; first rating of 1 on the second ascending run) and averages three crossings.
Their LRM/tLRM methods regress rating on current: `NRS = m·I + c`. TM differs from all three
regression methods (p < .001 for both thresholds) and they argue it overestimates through
habituation. Truncating the series at maximum R² used 25.2 steps instead of 42.4 and fitted better
(R² 0.81 vs 0.78).

**Badzińska et al. (2026)**, N = 401, compared three procedures on how close the delivered stimulus
lands to its target rating:

| | Calibration 1 | Calibration 2 | Calibration 3 |
|---|---|---|---|
| Structure | ascending only | ascending → exponential fit → 15 pseudorandom stimuli at 3 levels → refit | ascending → 2nd-degree polynomial → 17 pseudorandom stimuli at **7 levels** → refit |
| Scale, target | VAS 50/100 | NRS 5/10 | NRS 3, 5, 7 /10 |
| Planned − actual | 2.58 | 0.41 | 0.27 / 0.37 / 1.57 |
| % of target | 5.16 % | 8.2 % | 9 % / 7.4 % / **22.43 %** |
| Mean rank | 230.55 | 207.62 | **177.62** |

Kruskal–Wallis H(2) = 14.14, p < 0.001, η² = 0.03; the only surviving post-hoc contrast is
Cal 1 vs Cal 3, Z = 3.676, p = 0.001, r = 0.18.

*Reading the table.* The "% of target" row is (planned − mean actual)/planned per cell, on that
experiment's own scale — a difference of group means, so over- and under-raters cancel, and it is
**not comparable across columns**. The mean ranks come from a Kruskal–Wallis on **per-participant**
differences with everything rescaled to 0–100 first; that is the actual comparison. One ambiguity:
the paper defines the difference as signed, but Table 2 reports 2.58 for Cal 1 where
planned − mean actual is −2.58, so either the table shows magnitudes or the test used signed values
— the text does not resolve it. The effect is small and the three procedures differ in scale, pulse
structure and target simultaneously; the authors call for randomised allocation. Suggestive, not
decisive. Note also the 22.43 % error at the highest target: accuracy degrades at the top of the
range.

**Amir et al. (2022)** is often cited as the model here, and its structure is elegant — three fixed
anchor temperatures, then iterative linear regression placing each next stimulus at the temperature
predicted to give ratings 2, 5 and 8, refitting as it goes, 24 trials over 8 sites. **But their
objective is not ours.** They need the whole function: threshold (rating 2), tolerance (rating 8)
and fit quality are all outputs, so a third of their trials deliberately target the most painful end
of the scale. We need one point at 40 %, and every application above it is avoidable pain.

They also flag the circularity themselves: linear fits beat nonlinear ones possibly "because
temperatures were selected based on iterative linear regression, which might have encouraged
subjects to rate pain linearly". Any placement rule that concentrates stimuli at the model's
predicted targets both starves the fit of leverage and can train the participant into the assumed
shape.

Worth taking from Amir regardless:

- **The safety rule.** Never deliver a level at a site where that level or a lower one was already
  rated intolerable; lower it manually and **fit to the applied value, not the predicted one**.
- **The ordinal-consistency check** on ratings against intensity — cheap, assumption-free, and the
  robust half of their eligibility screen.
- **Reliability figures**, the only ones published for a calibrated pain level: ICC .658 threshold,
  .670 tolerance across visits (n = 171, median 23 days apart); r² itself ICC .171, and they advise
  against gating eligibility on it, which is where Świder's R² < 0.4 criterion came from. Caveats:
  the headline ICCs are effectively ICC(3,1) consistency, not the ICC(2,1) claimed, because the
  random-slope models did not converge; their within-subject CVs are computed on °C, an interval
  scale, so they do not transfer to a ratio scale like force; and tolerance drifted across visits
  (B = −.204, p = .011) in one testing environment but not the other.
- **The failure rates.** 88 of 342 (25.7 %) were ineligible: tolerance above range 12.6 %,
  dynamic range too compressed 10.6 %, ordinal inconsistency or low r² 4.7 %, threshold below range
  3.2 %. Their stimulus dimension had ~29 usable levels against our seven, so out-of-range should
  be expected at least as often here. It is not an edge case.

---

## 5. Simulation

Prose comparison ran out of resolution, so the candidates were simulated. `calibration_sim.py`
reproduces all of it.

### 5.1 Assumptions, stated plainly

- **Observer:** rating = 40 + s·(log₁₀F − log₁₀F₄₀) + N(0, σ), clipped to [0, 100]. In words: the
  participant's rating rises linearly with the logarithm of the applied force, passes through 40 at
  their own F₄₀, and each individual rating is perturbed by independent Gaussian noise. The three
  parameters are **F₄₀**, the participant's true 40 %-point in mN (the quantity being estimated);
  **s**, the slope in VAS points per log₁₀ unit of force (how sharply pain grows with force); and
  **σ**, the standard deviation of a single rating in VAS points (how repeatable one rating is).
- **The slope s is grounded, not invented.** Ng et al.'s Weber fraction of 0.88 gives 1 JND =
  0.274 log₁₀; in 2AFC a JND is d′ ≈ 1, so the mean shift over 0.274 log₁₀ equals √2·σ. With
  σ = 10 VAS points this gives **s = 51.6 VAS points per log₁₀ unit**, i.e. one filament step
  changes the rating by ~12.7 points. That ratio is the only strong assumption in the model.
- σ = 10 baseline, σ = 18 for a noisier reporter (s held fixed).
- Between-participant spread of F₄₀: 0.20 log₁₀ SD around the scenario median.
- Pre-S median F₄₀ = 600 mN; post-S median = 130 mN (from Scheuren's 2.7-step drop).
- 4000 simulated participants per cell.
- **Not modelled:** habituation, sensitisation across the run, anticipation, experimenter error,
  filament force error. All of these make every procedure worse; the ranking should survive them,
  but the absolute numbers are optimistic.

### 5.2 What each column means

**`apps` — mean number of monofilament applications per calibration.**
Counts both phases: the ascending search and the measurement repetitions. Averaged over the 4000
simulated participants, because the search length varies between people (someone whose F₄₀ is far
from the starting filament needs more steps to reach it). *Purpose:* the time and burden cost. At a
15 s ISI, duration ≈ apps × 15 s, and the calibration runs three times per session, so 11
applications means roughly 8–9 minutes of the session spent calibrating. This is the quantity being
traded against accuracy.

**`RMSE` — root-mean-square error of the estimate of F₄₀, in log₁₀ units of force.**
√(mean over participants of (log₁₀F̂₄₀ − log₁₀F₄₀)²), where F̂₄₀ is what the procedure returned and
F₄₀ is the participant's true value in the simulation. Expressed in log units because force is a
ratio scale and the ladder is log-spaced — an error of "50 mN" means something completely different
at 98 mN than at 2940 mN, whereas an error in log units is a constant *proportion*. Concretely,
RMSE = 0.065 means the estimate is typically out by a factor of 10^0.065 = 1.16, i.e. about 16 %.
RMSE = 0.222 means a factor of 1.67, about 67 %. *Purpose:* accuracy of the continuous mN value
that Table 1 treats as a dependent variable.

RMSE combines bias and variance. For the recommended strategy bias is negligible — checked
directly: −0.006, +0.000 and −0.006 log₁₀ at pre-S, post-S and post-S-noisy respectively, i.e.
under 0.03 filament steps — so RMSE here is effectively the standard deviation of the estimate.

**`steps` — the same RMSE divided by 0.246, the mean log₁₀ spacing between adjacent filaments.**
*Purpose:* to make the error interpretable against the hardware rather than as an abstract log
value. A value of 1.00 means the estimate is typically wrong by one whole filament. 0.26 means it
usually lands about a quarter of a filament away from the truth — which is close to the practical
floor, since one filament is 0.9 JND.

**`right filament` — percentage of simulated participants for whom the procedure picks the correct
filament.** Defined as: the estimate F̂₄₀, rounded to the nearest available filament, equals the
filament nearest to the true F₄₀. *Purpose:* this is the operational accuracy that actually matters
for the short protocol, which needs a physical object rather than a number. It is a coarser
criterion than RMSE and more forgiving of small errors, so the two columns can rank strategies
slightly differently — worth reading both. Note the ceiling: even a perfect estimator would not
reach 100 %, because participants whose true F₄₀ sits near the midpoint between two filaments are
close to a coin-flip.

**`≥40` — mean number of applications per calibration that produced a rating of 40 or above.**
That is, stimuli at or above the target pain level. *Purpose:* the pain cost. Some of these are
unavoidable — you cannot locate the 40 % point without crossing it — so the meaningful comparison
is between strategies rather than against zero. A strategy delivering 4 is doing roughly the
minimum; one delivering 11 is delivering seven avoidable painful stimuli per calibration, and
21 per session.

**`≥70` — mean number of applications producing a rating of 70 or above.**
Substantially more painful than needed. *Purpose:* separates procedures that briefly overshoot the
target from those that systematically deliver stimuli far beyond it. This is the column that rules
out the full 7-level series: 7.2 such applications per calibration at post-S, against approximately
zero for every ascend-based strategy.

### 5.2b What each strategy name means

- **"Ascend → …"** — a search phase that starts at a chosen filament and steps **up** while ratings
  are below 40 and **down** while they are at or above 40, stopping once the crossing is bracketed.
  Its trials count toward `apps` but are excluded from the estimate.
- **"3 adjacent × 3"** — the measurement phase: three filaments, adjacent on the ladder, three
  repetitions at each (nine applications), delivered in pseudorandom order. The three are the
  crossing filament and the two immediately below it, so the set brackets F₄₀ while keeping the
  stimuli on the low side. "2 adjacent × 3" is two filaments, three reps each.
- **"2 apart"** — the same but with the measurement filaments separated by two ladder steps instead
  of one, widening the lever arm for a fitted slope.
- **"fixed slope" vs "free slope"** — in `VAS = m·log₁₀(F) + c`, whether *m* is taken from the
  configured population value or estimated from that participant's own measurement trials. This is
  the distinction that turns out to matter most (§5.3).
- **"Rating-guided (Kesten) 12"** — 12 applications under Kesten's accelerated stochastic
  approximation (§4.2), each step proportional to the discrepancy between the rating and 40, with
  the step size shrinking only at reversals; estimate = geometric mean of the reversal forces.
- **"Binarised staircase 12"** — 12 applications, 1-up/1-down with rating ≥ 40 scored as "yes";
  estimate = geometric mean of the reversal forces.
- **"Full 7 levels × 2"** — method of constant stimuli: every filament in the 100–3000 mN range
  twice, pseudorandom order, no search phase.

Within each scenario every strategy is evaluated on **the same 4000 simulated participants**, so
the comparisons are paired and the differences are not sampling noise between rows.

### 5.2c Results

**Post-sensitisation, ascent started from an informed prior, σ = 10:**

| Strategy | apps | RMSE | steps | right filament | ≥40 | ≥70 |
|---|---|---|---|---|---|---|
| Ascend → 3 adjacent × 3, **fixed slope** | 11.1 | 0.065 | 0.26 | **71 %** | 4.8 | 0.2 |
| Ascend → 3 adjacent × 2, **fixed slope** | 8.1 | 0.079 | 0.32 | 65 % | 3.5 | 0.1 |
| Ascend → 2 adjacent × 3, **fixed slope** | 8.1 | 0.080 | 0.32 | 64 % | 4.2 | 0.2 |
| Rating-guided (Kesten), 12 | 12.0 | 0.086 | 0.35 | 64 % | 5.1 | 0.0 |
| Binarised staircase, 12 | 12.0 | 0.092 | 0.37 | 63 % | 5.8 | 0.2 |
| Ascend → 3 levels 2 apart × 3, free slope | 11.1 | 0.131 | 0.53 | 61 % | 3.6 | 0.2 |
| Full 7 levels × 2, free slope | 14.0 | 0.139 | 0.56 | 53 % | **11.5** | **7.2** |
| Ascend → 3 adjacent × 3, free slope | 11.1 | 0.222 | 0.90 | 57 % | 4.8 | 0.2 |

**Pre-sensitisation, ascent started at 255 mN rather than the bottom of the kit, σ = 10.** The
bottom-of-kit baseline is not shown as a row; for the top strategy it costs 17.6 applications
against 11.6 here, a larger saving than at post-S because the ascent has further to climb to reach
600 mN.

| Strategy | apps | RMSE | steps | right filament | ≥40 | ≥70 |
|---|---|---|---|---|---|---|
| Ascend → 3 adjacent × 3, fixed slope | 11.6 | 0.064 | 0.26 | 82 % | 4.0 | 0.2 |
| Ascend → 3 adjacent × 2, fixed slope | 8.6 | 0.079 | 0.32 | 78 % | 3.0 | 0.1 |
| Full 7 levels × 2, free slope | 14.0 | 0.062 | 0.25 | 84 % | 6.7 | 2.2 |
| Binarised staircase, 12 | 12.0 | 0.096 | 0.39 | 72 % | 5.4 | 0.2 |
| Ascend → 3 adjacent × 3, free slope | 11.6 | 0.130 | 0.53 | 72 % | 4.0 | 0.1 |

### 5.3 The finding that decides it

**Estimating the slope from the data is the dominant error source, and it is avoidable.**
Same trials, same stimuli — free slope gives RMSE 0.22–0.44 log₁₀; a fixed slope gives 0.065–0.14.
Three to five times better for zero extra pain.

The reason is structural: adjacent filaments differ by ~12.7 VAS points against 10–18 points of
rating noise, so the local slope is barely identifiable. Dividing by a noisy slope estimate to get
F₄₀ inflates the error enormously and occasionally produces absurd values.

And a fixed slope is robust to being wrong:

| Assumed slope, as a ratio of true | 0.50 | 0.70 | 0.85 | **1.00** | 1.20 | 1.50 | 2.00 |
|---|---|---|---|---|---|---|---|
| RMSE (log₁₀), post-S σ = 10 | 0.240 | 0.124 | 0.082 | **0.064** | 0.065 | 0.086 | 0.113 |
| Right filament | 31 % | 52 % | 65 % | **70 %** | 68 % | 60 % | 51 % |

A slope wrong by ±20 % costs essentially nothing. A slope wrong by a **factor of two** still beats
fitting the slope freely (0.113 vs 0.222). Shrinking the fitted slope toward the prior does not
help — any weight on the fitted slope makes things worse.

Two other results worth noting:

- **The full 7-level series is the most painful option by a wide margin** at post-S: 11.5
  applications at or above the target and 7.2 above 70 %, against 3–5 and ~0 for the ascend-based
  strategies. It is competitive on accuracy only at pre-S, where the target sits mid-ladder. Rule
  it out.
- **The informed-prior start saves ~3.5 applications** with no accuracy cost: for the recommended
  strategy at post-S, 14.6 applications starting from the bottom of the kit against 11.1 from an
  informed prior. The bottom-of-kit baselines are not tabulated above — both tables show only the
  informed or sensibly-started version — so those two figures come from the same simulation run and
  can be reproduced with `start=None` in `calibration_sim.py`.

---

## 6. Decision (S, 22 Aug 2026)

**Ascend from an informed prior → 3 adjacent filaments × 3 repetitions in pseudorandom order →
estimate with a fixed slope.**

Concretely:

1. **Search.** Start at the filament predicted by the prior (config default at pre-S session 1;
   thereafter the previous time point's estimate, shifted by a configured expected offset — about
   −2.7 steps from pre-S to post-S). Step **up** on a rating below 40, **down** on a rating at or
   above 40, until the crossing is bracketed. Log the start value.
2. **Measure.** **3 repetitions** at each of the three filaments — the crossing filament and the
   two immediately below it — in pseudorandom order, jittered ISI, site rotated each application.
   (Decided 22 Aug 2026; the 2-repetition variant saves 3 applications for RMSE 0.32 rather than
   0.26 filament steps and 65 % rather than 71 % correct filament.)
3. **Estimate.** Fit `VAS = m·log₁₀(F) + c` with **m fixed** at the configured population slope,
   using the measurement-phase trials only. Report F₄₀ as the continuous DV; use the nearest
   available filament for the short protocol. Store every force/rating pair so the analysis can
   refit differently later.
4. **Slope source.** Start from the simulated 51.6 VAS points per log₁₀ unit, and re-estimate it
   from pooled pilot data across participants — pooled estimation is stable even though
   per-participant estimation is not. Recheck it against accumulated data as the study runs.
5. **Budget.** 3 reps at post-S (~11 applications, RMSE 0.26 filament steps, 71 % correct
   filament); the same 3 reps at pre-S and post-I so the three estimates have equal precision.
   Hard cap the total at 25 applications.
6. **Out-of-range.** Boundary filament, `out_of_range` flag, tell the experimenter, continue —
   and expect it to fire in a meaningful fraction of sessions, so the analysis plan should state in
   advance what happens to those.
7. **Checks.** Ordinal consistency of ratings against force, as a rank correlation with a threshold
   rather than strict monotonicity (ratings genuinely plateau at the top post-S). Do not gate on
   R². Never re-apply a filament at or above one already rated intolerable at that site; if the
   experimenter substitutes a lower one, fit the applied value.

### Pros

- Fewest painful applications of any option reaching this accuracy: ~4–5 at or above target, ~0 at
  or above 70 %, against 11.5 and 7.2 for a full series.
- Best accuracy per application in every scenario tested, and the advantage widens with a noisier
  reporter.
- Predictable duration (~11 applications ≈ 2.8 min at a 15 s ISI), which matters when it runs three
  times inside a three-hour session.
- The predictable ascending phase, which is the part that inflates expectation, does not enter the
  estimate.
- Robust to a wrong slope prior, including badly wrong.
- Gives both required outputs: a filament and a continuous mN estimate.

### Cons, stated honestly

- **The fixed slope is an assumption about the participant.** If sensitisation genuinely changes
  the slope — and hyperalgesia plausibly steepens it — the same prior at pre-S and post-S is
  wrong in a *systematic* direction, which is worse than random error for a DV compared across time
  points. Mitigation: the stored force/rating pairs allow a pooled slope to be estimated per time
  point in analysis, and the runtime filament choice is insensitive to slope error anyway.
- **No published precedent for this exact combination.** The ascend-then-pseudorandom structure is
  Badzińska's; the fixed-slope estimator is not in any paper read. It is defensible from first
  principles and from the simulation, but it is our construction.
- **The simulated advantage rests on the s/σ ratio** taken from Ng et al.'s Weber fraction. If real
  ratings are far noisier relative to the slope than that implies, all procedures degrade and the
  ranking may narrow. Worth checking against the first few pilot participants — the pilot should
  record enough repeats at one filament to estimate σ directly.
- **The informed-prior start biases toward the prior** if the search is allowed to terminate too
  eagerly. The search must be able to move in both directions, and the start value must be logged
  so any bias is detectable.
- **71 % correct filament is not high.** It is a ceiling imposed by the hardware, not by the
  algorithm — adjacent filaments are 0.9 JND apart. Worth knowing that roughly a third of sessions
  will use a filament one step from optimal, and that the short protocol's ratings should be
  checked for floor and ceiling effects during piloting.

---

## 7. Protocol B — touch pressure

**Evidential status: this section is reasoning and arithmetic, not simulation.** §5 rests on 4000
simulated participants; §7 does not. Nothing in the literature read reports accuracy for a *range*
target, and method of adjustment cannot be usefully simulated the way a staircase can, because what
determines its accuracy is the participant's own search behaviour, which would have to be invented.
What can be computed is the time budget, and time is the binding constraint here.

### 7.1 The design — decided 22 Aug 2026

Hardware: pressure to 250 kPa, proportional valves, **five independently controlled channels**.
Resolution not yet known.

1. **Method of adjustment** on the **middle channel (channel 3)**, which serves as the reference,
   to find the **10 % and 90 %** intensity anchors. Stimulus on continuously while the
   participant adjusts. **Two adjustments per anchor**, one starting clearly below and one clearly
   above, averaged (see §7.3 on hysteresis).

   **Revised 23 Aug 2026 (S).** The targets were 10 %, 30 % and 80 %. They are now the two
   **labelled** anchors on the intensity scale — 10 % "just noticeable" and 90 % "just
   uncomfortable" — and **30 % and 80 % are interpolated between them**. The reason is that a
   participant can only be asked to adjust to a point the scale actually names; 30 % and 80 %
   carry no anchor label, so adjusting to them meant asking for a position on a line rather than
   for a sensation. Consequences:

   - **Two anchors instead of three**, so four adjustments and two verifications rather than six
     and three. The time budget in §7.2 improves; the figures there are not yet re-derived.
   - **The pleasantness window [P30, P80] is now derived rather than measured.** Both ends carry
     interpolation error. This is the real cost of the change, and it is the thing to watch in
     piloting.
   - **The control condition's 20 % target remains interpolated**, now between 10 % and 90 %
     rather than between 10 % and 30 %, so the rationale below still holds.
   - **90 % is "just uncomfortable" by construction**, so calibration will briefly produce an
     uncomfortable pressure. Bilaga 3a already tells participants this: "enstaka tryck kan
     upplevas som obehagliga innan rätt nivå är hittad."

   **Revised again the same day: the targets come from a fitted estimation run, not from the
   adjustments.** §7.3 below has always said that production and estimation differ
   systematically (Teghtsoonian & Teghtsoonian 1978) and that step 2 exists to measure the gap.
   If the gap is real, the targets belong on the estimation function rather than being
   spot-checked against it. So:

   - Step 1's adjustments now only **set a sampling bracket**, and drop to **one per anchor**.
   - Step 2 presents **ten amplitudes across that bracket in randomised order**, collects an
     intensity rating for each, fits **`rating ~ a + b·log(pressure)`**, and inverts it for P20,
     P30 and P80. Log because Stevens' power law makes rating near-linear in log pressure and
     the VAS is bounded at 100, so the top compresses; a straight line in linear pressure needs
     a tight enough bracket that curvature does not bite.
   - Fit **rating on pressure and invert** — pressure is controlled, rating is noisy. The other
     direction gives different numbers and is wrong here.
   - **The zero-pressure catch trials move into this run**, where randomised order hides them.
   - **Stage 1 failure acquires a definition** — flat, non-monotonic, or poor residuals — which
     is a per-participant quality gate the spot-check version could not provide.

   The time budget in §7.2 is **not re-derived**. One adjustment per anchor plus a ten-point
   estimation run is plausibly cheaper than the previous six adjustments and three
   verifications, but that is a claim to check against `SPEC.md` §21 open item 8, not an
   established figure. `SPEC.md` §20 item 8 is where that measurement lands.
2. **Estimation run — ten amplitudes across the bracket, randomised, fitted.** Not a per-anchor
   spot-check. See the revision note below.
3. **Match the other four channels to the reference** by adjustment at a single level, from two
   start points. Their full anchor sets are derived from the reference's by the fitted gain.
4. **Equalisation check** against the reference only — four comparisons, both orders, one channel
   then the reference with a **3 s hold**, prompting re-adjustment on mismatch.
5. **Pleasantness adjustment** using the actual pattern, looped continuously, with the adjustment
   range bounded to [P30, P80]. Two adjustments from different start points.

Channel 3 is the reference because it minimises the maximum distance to any other channel along the
arm and its sensitivity is likely to be intermediate rather than extreme.

Two things this design gets right that the earlier draft got wrong. The control condition's 20 %
target sits **between** the measured anchors, so it is interpolated rather than
extrapolated — which removes the failure mode that dominated Amir et al.'s exclusions. And
per-channel calibration is the correct response to five actuators over five sites with different
skin mechanics and different actuator coupling.

This is **scheme B** in §7.2: roughly 10.6–14.5 min per session, against 21–30 min for the
all-channels-all-anchors version.

### 7.2 Time budget

Assuming 30–45 s per adjustment and 12–15 s per pairwise comparison, both repeated from two start
points (see §7.3 on why):

| Scheme | Adjustments | Comparisons | Per session | Over 3 sessions |
|---|---|---|---|---|
| **A.** 3 anchors × 5 channels, all-pairs check | 30 | 20 | **21–29.5 min** | 63–88 min |
| **C.** 3 anchors × 5 channels, reference-based check | 30 | 8 | 18.6–26.5 min | 56–80 min |
| **B. ← chosen** anchors on a reference channel, others matched to it, reference-based check | 14 | 8 | **10.6–14.5 min** | 32–44 min |

Scheme A was the proposal as first stated. It costs 21–30 minutes of a three-hour session, every session.
Almost all of that is the 30 adjustments; the comparisons are cheap by comparison.

Two savings are available and they are close to independent:

- **Reference-based rather than all-pairs comparison.** Comparing every channel against one
  designated reference (4 pairs) instead of all pairs (10) makes them mutually equal by
  construction and transitively, and cuts the comparison count from 20 to 8. There is no
  information lost that the design uses.
- **Anchors on one channel, the rest matched by gain.** If the difference between channels is
  approximately a multiplicative gain on pressure — plausible if it comes from actuator coupling
  and skin mechanics rather than from differing slopes of the intensity function — then three
  anchors on a reference channel plus a single matching adjustment per remaining channel is
  sufficient, and the full anchor set for the other four can be derived. This is the large saving:
  30 adjustments down to 14, halving the total.

  **Scheme B is adopted, conditional on a pilot check**: run the full three anchors on the two
  channels expected to differ most and confirm the ratio between them is constant across the three
  levels. If it is not, fall back to scheme C (full anchors, reference-based check).

### 7.3 Method of adjustment — what it needs to be sound

Adjustment is a reasonable choice here: fast, natural on a continuous dimension, and the
participant does the searching. Its known weaknesses are all addressable:

- **Hysteresis and anchoring.** Settings depend on the starting point and the direction of
  approach. Standard fix, assumed in the budget above: **two adjustments per anchor, one starting
  clearly below and one clearly above, averaged.** This also yields the only available estimate of
  within-participant variability — if the two settings are far apart, the anchor is poorly defined
  for that person, which is worth logging.
- **Production is not estimation.** Asking someone to *adjust until this feels like 30 %* is
  magnitude production; the outcome measures in §3.9.1 are magnitude *estimation* (rate this
  stimulus). These are known to give systematically different exponents — the regression effect
  (Teghtsoonian & Teghtsoonian 1978). So an anchor produced at "30 %" will not necessarily be rated
  30 % when it is later delivered. **Mitigation: after adjustment, deliver the produced pressure and
  ask for a rating.** If it does not come back near target, that is measurable and correctable, and
  it costs one extra trial per anchor. The equalisation check in step 2 compares channels against
  each other but does not check either against the scale.
- **No stopping rule of its own.** The participant decides when they are done, so a time-out and a
  minimum-exploration requirement are needed, both logged.

### 7.4 The 3 s hold, and a mismatch worth anticipating

A 3 s hold is long enough to clear the inflation transient and to engage both rapidly- and
slowly-adapting responses, so it is a sensible basis for a static match. But **the intervention is
not static.** The Study 1 pattern is apparent motion at a CT-optimal velocity, so each actuator is
active only briefly, and if inflation rate differs between channels — different actuator volumes or
lengths — then channels matched at a 3 s static hold can still be mismatched during the moving
pattern.

Nothing later in the procedure fixes this. The final pleasantness adjustment corrects the *overall*
level but not the *relative balance* between channels, so an uneven-feeling pattern would survive.
Two options: equalise using short pulses at the pattern's own timing rather than a 3 s hold, or
keep the 3 s hold and add a single subjective check at the end — "does the movement feel even along
your arm?" — with the option to rebalance.

**Deferred to piloting** (S, 22 Aug 2026). The 3 s hold stands for now; whether it transfers to the
moving pattern is something the pilot can answer directly by asking. The software should support
the end-of-calibration evenness check and a rebalance path so that the option exists without a code
change.

### 7.5 Other spec consequences

- **Adjustment on two buttons — accelerating control (decided 22 Aug 2026).** The R400 gives up,
  down and confirm. A fixed rate cannot serve both reach and precision over 0–250 kPa: 25 kPa/s
  needs 10 s to traverse the range, 50 kPa/s crosses it in 5 s but moves 2.5 kPa per 50 ms tick.
  Instead the rate accelerates with hold duration. Suggested starting values, all in config and all
  pilot-tunable: a tap under ~150 ms moves **1 kPa** (0.4 % of range); holding starts at
  **5 kPa/s** after a 300 ms delay and ramps linearly to **50 kPa/s** over 1.5 s, then holds there.
  That gives fine positioning on taps and short holds, and traverses the full range in about **6 s**
  of continuous holding. Log every button-down and button-up event with timestamps, not just the
  final setting, so the whole search path is recoverable.
- **Bound the pleasantness adjustment to the window.** Stage 3 should map the adjustment range onto
  [P30, P80] found in stage 1, not onto 0–250 kPa. This is both what §3.9.1 specifies and a safety
  property.
- **Hard ceiling below the hardware maximum**, independent of the participant's adjustment, plus a
  rate limit so that holding the up button cannot ramp to maximum quickly.
- **Repeat the pleasantness adjustment from two start points** as well. Pleasantness is an inverted
  U rather than a monotone crossing, so peak location is intrinsically less well determined; if the
  two settings differ substantially, the peak is flat and the exact choice matters less — which is
  itself useful to know and to log.
- **Zero-pressure catch trials** during the comparison phase remain cheap and worth including.
- **Agency.** Calibration by adjustment gives the participant control over the stimulus in *every*
  condition. Enmalm et al. (2026) found pleasantness is higher when participants have agency over
  delivery, and Study 1's condition 2 is defined by exactly that contrast. Calibration agency is
  constant across conditions so it does not confound the comparison, but it may raise pleasantness
  across the board and compress the condition-2 effect. Worth noting in the analysis plan.

### 7.6 What this section still does not establish

No accuracy figure, no comparison against an alternative, and no evidence that adjustment
outperforms a short fitted series here. The pilot should record enough to settle three things: the
per-adjustment duration (which decides between schemes A, B and C), whether the between-channel
difference is a constant gain, and whether produced anchors are rated at their target level.

---

## 8. Filaments: practical

From Berquin et al. (2010):

- **Manufacturer forces deviate by −19.75 % to +17.61 %**, non-systematically. Weighing the set on
  a precision scale is his own recommendation and removes this. Record measured force per filament
  in config with the weighing date.
- **Humidity**: over 40–67 % RH one of his filaments changed force more than twofold. This lab runs
  **below 30 % RH**, outside his tested range, so his correction should not be applied. Log room
  temperature and RH at session start anyway so the question stays answerable.
- **Application standard**: perpendicular from ~3 cm, bent to about three-quarters of its extended
  length for ~1 s, no lateral movement, slow removal, site hidden.

From Scheuren et al. (2023): reposition ~1 cm after each application; ISI 13–17 s; rating cued 9 s
after the stimulus.

---

## 9. What remains unsupported

- **No published study repeats a calibration within a session.** Carryover between the three
  calibrations, and how a calibration performed immediately after experimental sensitisation should
  be interpreted, have no precedent. This is the least-supported part of the design and the pilot
  should be built to inform it.
- **No test–retest figures exist for a calibrated force**, only for thermal (Amir, ICC ≈ .66).
- **No paper calibrates a pain rating on a discrete monofilament ladder.**
- The simulation's observer model is a straight line in log force with homogeneous noise. Real
  ratings compress near both scale ends; clipping is modelled but compression is not.

---

## 10. References

- Adamczyk WM et al. (2022) *J Pain* 23:1823–1832. doi:10.1016/j.jpain.2022.07.001
- Amir C et al. (2022) Test-retest reliability of an adaptive thermal pain calibration procedure. *J Pain* 23:1543–1555. doi:10.1016/j.jpain.2022.01.011
- Badzińska J et al. (2026) Pain and precision. *J Pain* 42:106237
- Berquin AD et al. (2010) An adaptive procedure for routine measurement of light-touch sensitivity threshold. *Muscle Nerve* 42:328–338
- Cornsweet TN (1962) *Am J Psychol* 75:485–491. doi:10.2307/1419876
- García-Pérez MA (1998) *Vision Res* 38:1861–1881. doi:10.1016/S0042-6989(97)00340-4
- García-Pérez MA (2002) *Spatial Vis* 15:303–321. doi:10.1163/15685680260174056
- Kesten H (1958) Accelerated stochastic approximation. *Ann Math Stat* 29:41–59
- Leek MR (2001) *Percept Psychophys* 63:1279–1292. doi:10.3758/BF03194543
- Levitt H (1971) *JASA* 49:467–477. doi:10.1121/1.1912375
- Ng KKW et al. (2024) *eNeuro* 11(2). doi:10.1523/ENEURO.0412-23.2024
- Robbins H, Monro S (1951) A stochastic approximation method. *Ann Math Stat* 22:400–407
- Scheuren PS et al. (2023) *J Neurophysiol* 130:436–445. doi:10.1152/jn.00064.2023
- Teghtsoonian R, Teghtsoonian M (1978) Range and regression effects in magnitude scaling. *Percept Psychophys* 24:305–314. doi:10.3758/BF03204247
- Świder K et al. (2024) *Psychophysiology* 61:e14505. doi:10.1111/psyp.14505
- Treutwein B (1995) *Vision Res* 35:2503–2522. doi:10.1016/0042-6989(95)00016-X
- Yang H-H, Hsu Y-F (2024) *J Math Psychol* 120–121:102855. doi:10.1016/j.jmp.2024.102855
- Aesthesio® User Manual, DanMic Global LLC, rev. December 2018
