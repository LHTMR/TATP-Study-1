# RB2 — Which scale is each brush stroke rated on, and is the stroke standardised?

**Asked:** 23 Sep 2026. **For:** `docs/SPEC.md` §8.3 (brush allodynia), §10.6 (VAS questions), Milestone 3/4 protocol stream. **Confidence:** medium

## The question

`docs/SPEC.md` §8.3 says brush allodynia, in the primary and secondary zones at pre-S, post-S and
post-I, "uses the same protocol structure" as the short pinprick protocol: median of five, ISI
13–17 s, site rotated. It does not say which scale a brush stroke is rated on. §10.6 lists the pain
scale as "Pinprick pain — after each application", and the other scales (intensity,
pleasantness, relaxation, alertness) are about the garment or the participant's state. Nothing in
`config/study1.yaml` (`brush:` holds only `n_trials` and `n_sites`), `docs/DATA_SCHEMA.md` (the
`brush` table has one `rating_percent` column and no scale column) or `docs/LOG.md` settles it.
The experimenter instruction (`apply_brush: Brush the {region} zone at site {site}.`) states no
stroke length or duration.

**Not checked:** Bilaga 1 (the ethics folder was not available to this agent). If Bilaga 1 §3.6
names a brush scale or stroke, it overrides this report.

## What the evidence says

1. **The DFNS QST protocol rates brush strokes on the same 0–100 pain scale as pinprick.**
   Read in full. Dynamic mechanical allodynia (ALL) is tested "as part of" the mechanical pain
   sensitivity test. Three light tactile stimuli (cotton wisp ~3 mN, cotton-wool tip ~100 mN,
   Somedic brush 200–400 mN) are "applied with a single stroke of approximately 2 cm in length"
   and interleaved pseudorandomly with the seven pinprick stimuli, 10 s ISI. Participants "give a
   pain rating for each stimulus on a '0–100' numerical rating scale ('0' indicating 'no pain',
   and '100' indicating 'most intense pain imaginable')". ALL is the geometric mean of all
   tactile ratings. ALL "did not occur in healthy human subjects", so the normal value is 0.
   Rolke et al. 2006, *Pain* 123:231–243, [doi:10.1016/j.pain.2006.01.041](https://doi.org/10.1016/j.pain.2006.01.041)
   ([readable copy](http://www.immpact.org/static/meetings/Immpact9/background/Rolke.pdf)).
   Rolke et al. 2006 *Eur J Pain* 10:77–88 ([doi:10.1016/j.ejpain.2005.02.003](https://doi.org/10.1016/j.ejpain.2005.02.003))
   is the companion protocol paper. Only the search summary was read, and it agrees.
2. **The HFS literature from the Mainz group uses the same pain NRS for light tactile stimuli.**
   Klein et al. 2004 applied the same three tactile stimuli "with short strokes", balanced with
   pinprick, and subjects rated "on a numerical rating scale (NRS) ranging from 0 (nonpainful)
   to 100 (most intense pain imaginable)". HFS, but not LFS, "caused pain to light tactile
   stimuli in adjacent skin". *J Neurosci* 24:964–971, [doi:10.1523/JNEUROSCI.1222-03.2004](https://doi.org/10.1523/JNEUROSCI.1222-03.2004),
   PMC6729815. The abstract was read via Europe PMC. The methods were read only as a search
   excerpt, because the full-text server returned an error.
3. **Scheuren et al. 2023 did not test brush at all.** Read in full via Europe PMC (PMC10625835).
   Pinprick was rated on NRS 0–10 ("no pain" to "most intense pain imaginable"), cued by a tone
   9 s after the stimulus, ISI 13–17 s, in a repetitive phasic heat model. Light touch appears
   only as cotton-swab screening. So the ISI and cue timing that SPEC borrows for the brush come
   from a pinprick-only protocol. *J Neurophysiol* 130:436–445, [doi:10.1152/jn.00064.2023](https://doi.org/10.1152/jn.00064.2023).
4. **Werner et al. 2013 (heat–capsaicin phenotyping) mapped secondary hyperalgesia with a
   monofilament only, and did not rate the brush.** *PLoS One* 8:e62733, [doi:10.1371/journal.pone.0062733](https://doi.org/10.1371/journal.pone.0062733).
5. **Brush allodynia is induced much less reliably than pinprick hyperalgesia in surrogate
   models.** The systematic review states that "the ability of these models to induce dynamic
   mechanical allodynia was however substantially lower" than their ability to induce secondary
   hyperalgesia. Most studies report DMA as an *area*, not a rating. Quesada et al. 2021
   *Eur J Pain* 25:1389–1428, [doi:10.1002/ejp.1768](https://doi.org/10.1002/ejp.1768), PMC8360051.
   Read in part: the full text was fetched, but only some passages could be extracted.
6. **In the intradermal capsaicin model only 3 of 9 healthy controls reported brush-evoked pain.**
   Pain was rated on a computerised VAS, and more stroke repetitions was the only parameter that
   raised it. The authors call the model "unattractive" for tactile allodynia in healthy
   volunteers. Samuelsson et al. 2011 *Scand J Pain* 2:85–92, [doi:10.1016/j.sjpain.2011.01.003](https://doi.org/10.1016/j.sjpain.2011.01.003).
   Abstract only.
7. **In the heat/capsaicin model specifically, healthy subjects do report tactile-evoked pain**
   (n = 43), and stroking in the allodynic zone also reduced C-tactile hedonic processing.
   Liljencrantz et al. 2013 *Pain* 154:227–234, [doi:10.1016/j.pain.2012.10.024](https://doi.org/10.1016/j.pain.2012.10.024).
   Abstract only, so the scale used could not be confirmed.
8. **Stroke parameters.** DFNS fixes the stroke length (single stroke, ~2 cm) and the brush
   (Somedic, 200–400 mN), and gives no duration or velocity in the reference paper (item 1).
   Samuelsson et al. (item 6) found that repetition count, not stroke width or distance, changed
   pain. That argues for fixing *one stroke per application*. No source read here fixes a
   duration.

## Options

**A. The existing `pain` scale, identical to pinprick (the `vas.pain` key).** This is the DFNS and
Mainz convention (items 1–2). Brush and pinprick ratings are then on one scale and directly
comparable, and the question text ("How painful was the stimulus that you just felt on your hand?")
names no stimulus type. It also keeps the Bilaga 3a vocabulary, because the participant is never
told what the stimulus was. The 0 % "not at all painful" and 10 % "just painful" anchors already
separate painful from not painful strokes, so a painful-or-not question adds nothing. It costs
nothing: no new wording and no new screen. Risk: a floor effect. Many participants will rate 0 at
every time point (items 1, 5, 6), so the median of five will often be 0. That is an analysis-plan
matter, not a scale defect, because the outcome *is* whether light touch has become painful.

**B. A new unpleasantness scale.** This separates the affective component, and it is relevant to a
touch study (item 7). But the software has no such scale. It would need new, ethics-unsourced
participant wording, it departs from the DFNS convention, and it would no longer measure
allodynia as IASP defines it (pain to a normally non-painful stimulus). The `pleasantness` key
cannot be reused: its question asks about "the current touch from the garment". Showing it for the
brush would be false, and it would mix brush ratings into the garment-rating construct.

**C. A binary "was it painful?" question, then the pain VAS if yes.** This adds a screen type and a
branch, and it duplicates what the 10 % anchor already encodes. Not used by any protocol read here.

**D. Pain VAS plus a second scale per stroke.** This doubles the rating time inside a fixed
ISI, and in the interleaved blocks it gives a different rating burden from pinprick.

## Recommendation

**Option A: rate every brush stroke on the existing `vas.pain` scale, the same key, question and
anchors as pinprick. No new scale is needed.** It is the only convention the openly readable
protocol literature supports (Rolke 2006; Klein 2004). It adds no wording, and it keeps brush and
pinprick ratings commensurable. Record the scale in the data anyway: either a `scale` column on
`brush`, or a line in `DATA_SCHEMA.md` stating that `rating_percent` is on the pain scale. Then an
analyst never has to infer it.

**Stroke, for the experimenter instruction:** one single stroke of about 2 cm per application
(DFNS, Rolke et al. 2006), in one direction, with no repeated strokes, because repetition raises
pain (Samuelsson 2011). Put the length in `config/study1.yaml` (e.g. `brush.stroke_length_cm`),
sourced to Rolke 2006. **The literature read here fixes no stroke duration.** A duration of 1–2 s
is common practice but unsourced here. Leave it out of the instruction, or give it a
clearly-marked placeholder and an open item, until Bilaga 1 or the DFNS instruction manual is
checked.

Notes for the analysis plan (`docs/LOG.md` §3):
- Expect many zero medians. DFNS summarises ALL as a geometric mean. Log-transforming zeros needs
  an offset, and the plan should state which one before the data exist. The usual DFNS practice
  is a small constant, which should be verified against Rolke 2006 *Eur J Pain*.
- A 2 cm stroke over 1–2 s is 1–2 cm/s, inside the CT-optimal velocity range. The brush is
  therefore itself a partly CT-targeted stimulus, applied equally in all conditions, so it cannot
  confound the comparison. The write-up should mention it.
- The 9 s rating-cue delay comes from pinprick (Scheuren 2023). DFNS rates the tactile stimuli
  straight away. Whether the brush uses the same delay is a separate implementation choice that
  this report does not settle.

## What would change this

- **Bilaga 1 §3.6 naming a different scale or stroke for the brush.** It overrides this report.
- The Liljencrantz 2013 or Meeker 2021 full text showing that heat/capsaicin studies rate the
  brush on unpleasantness as the primary outcome. Even then, pain would stay primary here.
  Unpleasantness would be added only if S wants it.
- A pilot in which almost no one reports brush pain post-S. The outcome would then be better
  analysed as a proportion of painful strokes, or dropped in favour of area mapping, and the scale
  would stay the same.
