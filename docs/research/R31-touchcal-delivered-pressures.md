# R31 — At what level are channels matched, and what pressure does each condition deliver per channel?

**Asked:** 2026-09-23. **For:** `docs/SPEC.md` §9 steps 3–6, §12.2 (sham); comparison doc §7.1–7.2;
Milestone 3 (Protocol B). **Confidence:** medium. The recommendation mostly follows from the
settled design and from Stevens' law. The literature does not address this exact choice, and
two of the sources on force and pleasantness could be read only as abstracts.

## The question

Protocol B fits `rating ~ a + b·log(pressure)` on channel 3 and inverts it for P20, P30 and P80
(§9 step 2). The other four channels are matched to channel 3 by adjustment at **one** level,
from two start points. That gives a multiplicative gain `gain_c`, which is then applied across
the whole P20–P80 range (§9 step 3; scheme B, comparison doc §7.2). The pleasantness adjustment
(step 5) then sets a level inside the fitted [P30, P80]. The spec does not say:

- **A.** which reference level the single matching adjustment (and the step 4 equalisation
  check) is done at;
- **B.** what pressure each condition delivers on each channel, how the two pleasantness settings
  are combined, and whether `ct_targeted` and `participant_preferred` must share a level.

## What the evidence says

**1. Under Stevens' law, a constant gain on pressure is a pure shift in log pressure, and a
failure of that assumption grows with distance from the match level.** If
ψ = k·p^β ([Stevens 1957](https://doi.org/10.1037/h0046162), DOI 10.1037/h0046162), then a channel
whose coupling scales pressure by g has rating function a' + b·log p with the **same slope b**. Only
the intercept moves. Scheme B's assumption is exactly "same slope, shifted intercept". Suppose it
fails, because a channel's effective exponent differs from the reference's by a fraction δ_c.
Then the log-pressure error of a gain matched at level m, applied at level x, is
δ_c·(log x − log m). On the reference fit, log x − log m = (R_x − R_m)/b. So **the rating error
at a delivered level is about δ_c × (the VAS distance between the delivered level and the match
level)**. This is algebra on the spec's own fit form, not a published result. It is the reason
the match level matters at all. It also says the level should be chosen by its distance *in
rating units* (equivalently, in log pressure) from the levels actually delivered.

**2. The levels actually delivered are P20 (sham) and one level inside [P30, P80] (both touch
conditions).** SPEC §12.2 and `config/study1.yaml` `sham_target_intensity_pct: 20.0`; SPEC §9
step 5. The level that minimises the worst-case error over {P20} ∪ [P30, P80] is **R = 50, that
is P50**. The level that minimises it over [P30, P80] alone is R = 55. Because rating is linear
in log p, that is **exactly the geometric mean √(P30·P80)**. The *arithmetic* mean (P30+P80)/2
sits higher on the fit. For a window ratio P80/P30 of 3 it is at about R = 61.5, and for a ratio
of 5 at about R = 64. The distance to P20 is then 41–44 VAS points, against 30 for P50.

**3. Pleasantness depends on velocity far more than on force, and within the gentle range more
force tends to be less pleasant.** Velocity: CT firing and pleasantness both peak at 1–10 cm/s
([Löken et al. 2009](https://doi.org/10.1038/nn.2312), DOI 10.1038/nn.2312, *abstract only*). The
same inverted-U over 0.3–30 cm/s appears on the forearm and other hairy sites
([Ackerley et al. 2014](https://doi.org/10.3389/fnbeh.2014.00054), DOI 10.3389/fnbeh.2014.00054;
[PMC3928539](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3928539/)). Force: secondary sources
report that Löken et al. found CT firing and pleasantness largely insensitive to brush normal
force at 0.2–0.4 N. **I could not read this in the primary text**, so treat it as unconfirmed.
Lighter stroking was rated more pleasant than heavier stroking at every skin site tested, and
forearm hairy skin was the most sensitive to hardness
([Yu et al. 2019](https://doi.org/10.1016/j.heliyon.2019.e02141), DOI 10.1016/j.heliyon.2019.e02141,
open access). With an eight-actuator **pneumatic** array on the forearm, speed was the strongest
factor, and higher indentation pressure had moderate effects that *reduced* pleasantness
([Kommuri et al. 2025](https://doi.org/10.1109/toh.2025.3611671), DOI 10.1109/toh.2025.3611671,
*abstract only*, via [Europe PMC](https://europepmc.org/article/MED/40966146)). The "inverted U in
force" is therefore real only over the whole range from nothing to firm. Inside a window that
starts at 30 % intensity, the pleasantness function is plausibly flat-topped or falling. That
favours settings in the **lower half** of [P30, P80], which pulls further toward P50 than toward
P55. It also means the two pleasantness settings may legitimately be far apart. Comparison doc
§7.5 already anticipates this.

**4. Method-of-adjustment and magnitude-production settings on a ratio-scale stimulus are
averaged geometrically.** Group magnitude-production functions are conventionally obtained by
pooling responses with **geometric means** and regressing log response on log stimulus
([Rule 1969](https://doi.org/10.1007/BF02289346), DOI 10.1007/BF02289346, *abstract only*). The
underlying reason is Weber's law: the spread of settings scales with their magnitude, so errors
are roughly multiplicative, i.e. log-normal. For haptic force and pressure this is standard
([Jones & Tan 2013](https://doi.org/10.1109/toh.2012.74), DOI 10.1109/toh.2012.74, review; *abstract
only*). A geometric mean is also the only averaging that agrees with the spec's own log-pressure
fit. The mean of two settings in log p is the mean of their predicted ratings. **The practical
difference is small.** For settings in a ratio r, arithmetic/geometric = (1+r)/(2√r): 1.004 at
r = 1.2, 1.02 at r = 1.5, 1.06 at r = 2. It matters only when the two settings disagree
strongly, which is exactly when a flat peak (point 3) makes the choice matter least.

**5. Production is not estimation.** Adjusting to a level and rating a level give systematically
different functions, the regression effect
([Teghtsoonian & Teghtsoonian 1978](https://doi.org/10.3758/BF03204247), DOI 10.3758/BF03204247;
comparison doc §7.3). This does not bias a *matching* adjustment, which compares two stimuli
directly and involves no scale. It is why the match level should be a **fitted** reference value,
as SPEC §9 step 3 already requires ("chained off the fitted reference values").

**6. Preference is chosen at the calibrated intensity.** SPEC §9 step 6 presents the candidate
patterns "at their calibrated intensity". The participant's pattern choice is therefore
conditional on the step 5 level. Delivering the chosen pattern at that same level is internally
consistent. Delivering it at any other level is not.

## Options

**Part A: match level (step 3, and the step 4 check at the same level)**

| Option | Cost | Risk to validity |
|---|---|---|
| **A1. P50 of the reference fit** | Add 50 to the inverted targets (a `p50_kpa` in `touchcal_fit`, and 50 in `derived_pct` or a separate key) | Minimax error over every delivered level, both P20 and the window. Always inside the sampled bracket. A mid-range level, where discrimination is best and exposure is moderate |
| A2. Geometric midpoint of [P30, P80] (= P55) | The same, with 55 | Best for the touch conditions alone, but 35 VAS points from P20 rather than 30. Practically indistinguishable from A1 |
| A3. Arithmetic midpoint of [P30, P80] | None beyond A2 | Sits at about R = 62–64. It is further from P20 and from where pleasantness settings probably land (point 3). No advantage |
| A4. The pleasantness setting itself | Reorders steps 3 and 5 | **Not feasible.** Step 5 loops a pattern over all five channels, so it needs the gains first. Using it would make the calibration circular. It also contradicts the settled order |

**Part B: delivered pressure per channel c**

| Option | Risk |
|---|---|
| **B1. Sham = `gain_c` × P20. Both touch conditions = `gain_c` × L, with L = geometric mean of the two pleasantness settings (on the reference scale). The same L for `ct_targeted` and `participant_preferred`** | Pressure is held constant between the two conditions the study compares, so pattern (and the agency manipulation, §12.3) is the only difference. This is consistent with the preference having been chosen at L (point 6) |
| B2. As B1, but with an arithmetic mean | Differs from B1 by ≤ 2 % unless the settings are > 1.5× apart. Inconsistent with the log fit |
| B3. A condition-specific level (e.g. a pleasantness adjustment on the preferred pattern, used only in that session) | **Excluded.** A calibration step that differs by condition breaks §16. If it were run in every session to avoid that, the two touch conditions would differ in pressure as well as pattern, and the contrast would be confounded |

On the blinding premise: §16 forbids the *procedure* or anything *displayed* from differing
between conditions. It does not by itself forbid the delivered pressure from being a function of
the condition. B1's reason is therefore measurement validity (one manipulated factor) plus point
6. Blinding is not the argument. B1 is also the only option in which nothing condition-dependent
happens before delivery.

## Recommendation

**Part A: A1.** Do the single matching adjustment on each non-reference channel against the
reference delivered at **fitted P50**, and run the step 4 equalisation check at the same level.
Compute `gain_c = √(m_c1 · m_c2) / P50_ref`, where m_c1 and m_c2 are the two matching settings,
i.e. average in log pressure.

**Part B: B1.** On every channel c:

- `sham` delivers `gain_c · P20_ref`, static;
- `ct_targeted` and `participant_preferred` both deliver `gain_c · L`, where `L = √(s1 · s2)` is
  the geometric mean of the two step 5 settings, expressed on the reference channel's scale. The
  step 5 adjustment range on channel c is correspondingly `gain_c · [P30_ref, P80_ref]`.

Both raw pleasantness settings are already logged in `touchcal_adjust`, so an arithmetic-mean
sensitivity analysis stays possible after the fact. Nothing else needs recording.

**Two consequences the main session must handle. Neither is a research question.**

1. **The pattern looped during step 5 must be the same in every session, whatever the
   condition.** This is required by §16, and by step 6 coming after step 5. The spec says only
   "the actual pattern", and `config/study1.yaml` has no key for it. If it is the 3 cm/s sweep, L
   is tuned to the `ct_targeted` pattern, which is a small asymmetry in that condition's favour.
   Log that choice as a known limitation in `docs/LOG.md`, or raise it with S. This report does not
   decide which pattern.
2. **Sham spatial summation (unsourced reasoning, for the pilot).** P20 is fitted on one channel,
   but `static_sham` holds all five on (LOG N6.3). Five sites at a single-site 20 % level may be
   rated above 20 %. The in-condition intensity ratings will show it.

## What would change this

- **The pilot check in comparison doc §7.2** (full anchors on the two most different channels). If
  the ratio between channels is not constant across levels, scheme B falls back to scheme C and
  the match level becomes moot. If the ratio drifts but stays usable, the drift says whether P50
  or a level nearer the observed pleasantness settings keeps the errors smaller.
- **Where the step 5 settings actually land.** If pilot settings cluster near P70–P80, rather than
  low in the window as point 3 predicts, the match level should move up to the geometric
  midpoint of the window (A2).
- **The Löken et al. 2009 full text and the Kommuri et al. 2025 full text.** Either could show a
  force effect on pleasantness that interacts with velocity. That would argue for a
  pattern-specific level, which would need a blinding-safe design to go with it.

**For S:** nothing here weakens blinding or sets a hardware limit. One boundary does touch S's
limits. `gain_c · P80_ref` on a weakly coupled channel could exceed the hard ceiling (comparison
doc §7.5). The software should refuse or flag that rather than silently clip it. The ceiling
value itself is S's. The step 5 pattern choice (consequence 1) may also be worth S's eye.
