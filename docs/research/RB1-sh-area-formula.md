# RB1 — Which formula turns the four mapped SH border distances into an area in mm²?

**Asked:** 2026-09-23. **For:** `docs/SPEC.md` §8.4; `docs/DATA_SCHEMA.md` `sh_area` table
(`area_mm2` from `distance_1_mm`..`distance_4_mm`). **Confidence:** medium

## The question

§8.4 says the experimenter maps the secondary hyperalgesia (SH) border along four linear paths.
The paths go inward in 5 mm steps at 1 s intervals. The experimenter marks the border, measures
it with a ruler and types four distances, and "the software computes the area in mm² and stores
both". The spec gives no formula. It also does not say where each distance is measured from: the
centre of the primary (heat/capsaicin) zone, or its edge. Nor does it say which path is opposite
which. All three affect `area_mm2`.

**Not read for this report:** Bilaga 1 §3.6.2 itself. The ethics folder is not a working
directory of this session. If Bilaga 1 names a formula or a measurement origin, that overrides
this report. The main session should check this with
`make ethics ARGS="Bilaga1_Forskningsplan_V2.docx --grep area --context 4"` (and again with
`--grep distance`).

## What the evidence says

### 1. The TATP procedure is the heat/capsaicin model's procedure

TATP uses heat plus 0.075 % capsaicin (SPEC §4 table). Its mapping is four paths, 5 mm steps,
1 s intervals and "definite change in sensation". That is the Petersen & Rowbotham
heat/capsaicin mapping, as carried on by the Rowbotham/Petersen and Dahl groups:

- **Petersen & Rowbotham 1999**, *NeuroReport* 10:1511–6,
  [doi:10.1097/00001756-199905140-00022](https://doi.org/10.1097/00001756-199905140-00022).
  This is the originating model paper. Only the abstract was readable, and it does not give the
  area formula. Later papers cite it for the rectangle method below.
- **Cavallone, …, Petersen, Gereau 2013**, *J Pain Res* 6:771,
  [doi:10.2147/JPR.S53437](https://doi.org/10.2147/JPR.S53437), open access
  ([PMC3827105](https://europepmc.org/article/PMC/PMC3827105)).
  - Mapping: "four linear paths between the thermode outline and: 1) the antecubital fossa;
    2) the wrist; 3) the lateral forearm; and 4) the medial forearm … in 5 mm steps at
    1-second intervals".
  - Area: "calculated … as the distance between the farthest points marked on the
    rostral/caudal axis multiplied by the distance between the farthest points marked on the
    medial/lateral axis". **This is a rectangle whose sides are the mark-to-mark spans.**
- **Werner, Petersen, Rowbotham, Dahl 2013**, *PLoS One* 8:e62733,
  [doi:10.1371/journal.pone.0062733](https://doi.org/10.1371/journal.pone.0062733)
  ([PMC3650051](https://europepmc.org/article/PMC/PMC3650051)).
  - Heat/capsaicin mapping "along 4 linear paths arranged in 90° angles around the stimulation
    center, in 5-mm steps at 1-s intervals".
  - "The transverse and longitudinal axes were measured for surface area calculations"
    (rectangle).
  - The same paper's burn-injury model uses 8 lines and an octagon. So one group uses different
    geometry for different path counts.
- **Hansen et al. 2016**, *PLoS One* 11:e0155284,
  [doi:10.1371/journal.pone.0155284](https://doi.org/10.1371/journal.pone.0155284) (Dahl group,
  brief thermal sensitisation, which uses the same mapping).
  - "4 linear paths arranged 90° around the center of the heat-stimulation … steps of 5 mm with
    1-second intervals towards the center".
  - "The transverse and longitudinal axes were measured … for rectangular area calculation."
  - Explicitly: **"The area of the thermode (2.5x5 cm) was not subtracted from the total
    area."** It cites Petersen 1999.
- **Hansen et al. 2018**, *PLoS One* 13:e0201642,
  [doi:10.1371/journal.pone.0201642](https://doi.org/10.1371/journal.pone.0201642). Uses the same
  wording, "rectangular area calculation", and cites Dirks, Petersen & Dahl 2003, *J Pain*
  4:122, [doi:10.1054/jpai.2003.10](https://doi.org/10.1054/jpai.2003.10). Only the abstract of
  Dirks 2003 was readable.

### 2. Other models use other geometry, mostly because they use 8 lines or tracing

- **Ellipse** from two perpendicular diameters, (D/2)(d/2)π: Rempe et al. 2014, *PLoS One*
  9:e112325, [doi:10.1371/journal.pone.0112325](https://doi.org/10.1371/journal.pone.0112325).
  This is topical capsaicin.
- **Octagon, thermode subtracted**: Ringsted et al. 2015, *J Neurosci Methods* 256:74,
  [doi:10.1016/j.jneumeth.2015.08.018](https://doi.org/10.1016/j.jneumeth.2015.08.018),
  [PMC4651781](https://pmc.ncbi.nlm.nih.gov/articles/PMC4651781/). This is a burn injury with 8
  lines and vector software, "total area with the area of the thermode subtracted". Werner 2013's
  burn model is the same.
- **Spline through 8 radii measured from the electrode centre**: Lebrun et al. 2025, *PLoS One*,
  [doi:10.1371/journal.pone.0318934](https://doi.org/10.1371/journal.pone.0318934). This is the
  van den Broeke/Mouraux HFS line. No subtraction is mentioned.
- **Tracing of 8-angle marks onto a transparency, then scanned**: Scheuren et al. 2023,
  *J Neurophysiol* 130:436, [doi:10.1152/jn.00064.2023](https://doi.org/10.1152/jn.00064.2023),
  [PMC10625835](https://pmc.ncbi.nlm.nih.gov/articles/PMC10625835/). This is repetitive phasic
  heat.
- Quesada et al. 2021's review (*Eur J Pain* 25:1389,
  [doi:10.1002/ejp.1768](https://doi.org/10.1002/ejp.1768)) is open access, but its full text
  could not be fetched in this session. Whether it recommends a formula was not checked.

**Summary:**
- With **four orthogonal paths in the heat/capsaicin model**, every open-access source found
  uses the **rectangle of the two axis spans**. The primary zone is **included** (not
  subtracted), which is explicit in Hansen 2016.
- Ellipses, polygons and tracing appear with other models or with 8 lines.

### 3. The geometry: with a common centre, candidates (a)–(c) differ only by a constant

Let the radii from the primary-zone centre be p, l, d, m (proximal, lateral, distal, medial,
going round), and let S = (p + d)(l + m). Then:

| Candidate | Formula | Equals |
|---|---|---|
| rectangle (heat/capsaicin convention) | (p+d)(l+m) | 1·S |
| rhombus / sum of four triangles | ½(pl + ld + dm + mp) | ½·S |
| ellipse | π·((p+d)/2)·((l+m)/2) | (π/4)·S |
| four quarter-ellipses | (π/4)(pl + ld + dm + mp) | (π/4)·S, **identical to the ellipse** |

This holds because pl + ld + dm + mp = (p + d)(l + m). So **candidates (b) and (c) are the same
number**, and (a) and the rhombus are fixed multiples of it.

- **Unaffected by the choice:** any within-participant ratio (post-S/pre-S, post-I/post-S), any
  log-ratio and any correlation.
- **Affected by the choice:** the absolute mm² value, and absolute differences, which scale by
  the constant. So the choice matters only for comparing against published norms, and the
  norms for this model are rectangles.

### 4. What does change the answer non-proportionally: the measurement origin

Suppose the ruler is laid from the **edge** of a primary zone that measures L (proximal–distal)
by W (medial–lateral). Then:

- the rectangle becomes (p + d + L)(l + m + W);
- subtracting the primary zone takes off a further L·W.

Both are additive terms, not scale factors. They change the relative change between time points,
especially when the SH zone is small (for example at pre-S, if any border is found). Without L
and W the area cannot be computed at all.

In the rectangle sources the side is the **mark-to-mark span** (Cavallone: "distance between
the farthest points marked"; Hansen: "axes measured"). The span equals p + d when radii are
taken from the centre. So measuring each path from the **centre** reproduces the published
quantity exactly, and needs no primary-zone dimensions.

## Options

1. **Rectangle, radii from the primary-zone centre, primary zone not subtracted:**
   `area_mm2 = (d_proximal + d_distal) × (d_medial + d_lateral)`.
   - Cost: the centre of the primary zone must be marked on the skin (a pen dot at
     sensitisation) and the experimenter script must say to measure from it.
   - Validity: matches the model's literature (Petersen/Dahl lineage) and needs no extra input.
     It overstates the true, roughly elliptical area by about 4/π, but that is a constant and
     does not affect within-participant comparisons.
2. **Ellipse, (π/4)(d_p + d_d)(d_m + d_l), from the centre.** Also the same number as the
   quarter-ellipse sum.
   - Cost: none extra.
   - Validity: arguably closer to the true shape, but not the convention for this model, so
     published comparisons need a ×4/π conversion. Otherwise it behaves exactly like option 1.
3. **Rectangle or ellipse with radii from the primary-zone edge**, adding L and W, with or
   without subtracting L·W.
   - Cost: two more config values (the primary-zone footprint, placed consistently each time),
     plus a decision on subtraction.
   - Risk: an additive term, which distorts ratios. A mis-set footprint biases every area. Only
     worth doing if Bilaga 1 prescribes measuring from the edge.
4. **Rhombus (½·S).** Not used in any source found, and it underestimates. No reason to choose
   it.

## Recommendation

**Option 1.** The rectangle is the convention of the model TATP actually runs:

- the four-path, 5 mm, 1 s procedure is Petersen & Rowbotham's;
- every open-access four-path heat/capsaicin paper computes the rectangle of the axis spans;
- Hansen 2016 states that the thermode area is not subtracted;
- measuring radii from the centre makes the four typed distances sum to exactly those spans, so
  nothing else is needed;
- the rectangle, rhombus and ellipse differ only by a constant, so this choice cannot bias a
  within-participant effect, and the four raw distances are stored anyway.

For the software:

- give the paths anatomical names, not bare numbers, so that opposite pairs are fixed;
- store distances measured **from the centre of the primary zone**;
- compute (proximal + distal) × (medial + lateral);
- if `distance_1..4` must stay numbered, fix the order around the circle in config (for
  example proximal, lateral, distal, medial), so that 1↔3 and 2↔4 are opposite and
  `area_mm2 = (distance_1_mm + distance_3_mm) × (distance_2_mm + distance_4_mm)`.

Two consequences for the main session:

- **`distance_plausible_min_mm: 1.0` is too low for centre-origin radii.** A border inside
  half the primary-zone width is implausible. Whether to tighten it is the main session's
  call.
- The experimenter's `instructions.mapping_script` must say where the ruler goes. That is
  experimenter-facing, not participant-facing.

## What would change this

- **Bilaga 1 §3.6.2** naming a formula, or saying to measure from the zone edge. Then use
  option 3 with L and W from the approved protocol. Whether to subtract should follow what
  Bilaga 1 says; if it is silent, do not subtract, following Hansen 2016.
- The full text of Petersen 1999 or Dirks 2003 showing a different calculation for the
  model's original validation.
- Pilot mapping showing that experimenters cannot reliably find the centre after the capsaicin
  is removed. Then measuring the two mark-to-mark spans directly (Cavallone's wording) gives
  the same rectangle, at the cost of the four-radius asymmetry detail.
