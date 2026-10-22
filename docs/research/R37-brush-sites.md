# R37 — How many brush sites per zone, what stroke, and how they rotate (SPEC §8.3)

**Asked:** 22 Oct 2026. **For:** `docs/SPEC.md` §8.3 (brush allodynia, primary and secondary), Milestone 6 (pilot/demo-feedback-2). **Confidence:** low for the site counts and placement (no study tests them; they follow from geometry and indirect evidence), medium for the stroke (one stroke of about 2 cm).

## The question

SPEC §8.3 says brush allodynia "uses the same protocol structure" as the short pinprick protocol:
median of five, ISI 13–17 s, site rotating on every application. `config/study1.yaml` gives
`brush.n_trials: 5`, `brush.n_sites: 8`, one value for both zones. `apply_brush` tells the
experimenter to make "a single stroke of about 2 cm" (RB2, LOG N7.B6). The primary zone is the
thermode footprint, about 25 × 50 mm (Hansen et al. 2016 give the same 2.5 × 5 cm thermode;
see RB1). Eight separate 2 cm strokes do not fit in it without overlapping. The pinprick value of
8 sites was carried over to the brush without regard to stroke size. The spec does not say how
many brush sites each zone has, where they lie, or whether the sequence repeats at each time
point.

**Bilaga 1.** This agent could not open `Bilaga1_Forskningsplan_V2.docx`: no shell was
available, and `Read` cannot open `.docx`. The only text available is the quotation in LOG N7.B6,
checked on 24 Sep 2026, from Bilaga 1 §3.6.3: *"The protocol is otherwise the same as the short
protocol for pinprick pain."* Nothing seen from Bilaga 1 fixes the number of brush sites, the
stroke length or the brush width. If §3.6.3 does fix any of them, it overrides this report. The
main session should grep it for `brush`, `stroke` and `site` before acting
(`make ethics ARGS="Bilaga1_Forskningsplan_V2.docx --grep brush --context 3"`).

## What the evidence says

Full text was read from the PDFs in the ethics folder (`support_documents/articles/`), except
where marked.

1. **DFNS: five strokes per tactile stimulus, one stroke each, 1–2 cm, within one test area, ISI
   about 10 s.** "The three tactile stimuli were applied five times each with a single stroke of
   approximately 1–2 cm in length over the skin. They were intermingled with the pinprick stimuli
   in balanced order." Rolke et al. 2006, *Eur J Pain* 10:77–88,
   [doi:10.1016/j.ejpain.2005.02.003](https://doi.org/10.1016/j.ejpain.2005.02.003). The reference
   paper says "a single stroke of approximately 2 cm in length", with "All stimuli … applied with
   a ~10 s inter-stimulus interval" and 50 stimuli "delivered at each site", where a site is the
   test area (for example the dorsum of the hand). Rolke et al. 2006, *Pain* 123:231–243,
   [doi:10.1016/j.pain.2006.01.041](https://doi.org/10.1016/j.pain.2006.01.041). **Neither paper
   names sub-sites within the test area for the strokes.** By contrast, the wind-up test is
   explicitly done "at five different skin sites within the same body region" (EJP 2006), so where
   DFNS wants separate sites it says so. Brush: Somedic, 200–400 mN.
2. **Heat model, brush rated inside the primary zone and in adjacent skin.** Jürgens et al. 2014
   applied the DFNS tactile set (Somedic brush), "five times in a randomized sequence", in the
   heat-conditioned central zone (a 30 × 30 mm thermode footprint) and in the adjacent zone P1.
   Both showed significant dynamic mechanical allodynia, but it was tiny: geometric means after
   conditioning were 0.21 (central) and 0.14 (P1) on a 0–100 NRS (Table 1). The paper names no
   sub-sites within the 9 cm² central zone. *PLoS One* 9:e99507,
   [doi:10.1371/journal.pone.0099507](https://doi.org/10.1371/journal.pone.0099507)
   ([PMC4050052](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4050052/)). This is the only study
   found that rates the brush in a primary zone of about this size.
3. **Capsaicin, secondary zone: short strokes laid along a fixed distance from the primary
   zone.** Ziegler et al. 1999 used "short (1 cm) strokes", five per test, randomised with five
   pinprick forces. "To avoid stimulation of the zone of primary hyperalgesia, all stimuli were
   applied along the circumference of a semicircle of radius 15 mm surrounding the injection site."
   *Brain* 122:2245–2257, [doi:10.1093/brain/122.12.2245](https://doi.org/10.1093/brain/122.12.2245).
4. **Heat/capsaicin, secondary zone: the brush-allodynic area is small and lies close to the
   primary zone.**
   - Liljencrantz et al. 2014 (heat/capsaicin, 45 °C for 5 min, 0.075 %): tactile allodynia area
     391 ± 72 mm², against 1064 ± 118 mm² for punctate hyperalgesia. Strokes were made with a
     goat-hair brush 0.5 cm wide, over 5 cm, 10 per stimulus type, and brush pain was "minimal".
     *Neurosci Lett* 563:75–79,
     [doi:10.1016/j.neulet.2014.01.041](https://doi.org/10.1016/j.neulet.2014.01.041).
   - Petersen & Rowbotham 1999: after capsaicin, brush area 100 cm² against 162 cm² for von Frey.
     The brush was used only for area mapping (a foam brush), not rated per stroke. *NeuroReport*
     10:1511–1516, [doi:10.1097/00001756-199905140-00022](https://doi.org/10.1097/00001756-199905140-00022).
     The full text is in the ethics folder, although the README "To fetch" table still lists this
     paper as abstract-only for R36.
   - Cavallone et al. 2013 likewise use a foam brush for area only.
     [doi:10.2147/JPR.S53437](https://doi.org/10.2147/JPR.S53437).
5. **Repetition and length raise brush pain.** The Samuelsson thesis abstract (neuropathic
   patients) reports that "increased brushing length, increased number of strokes, lower stroking
   velocity and increased brushing force" raised total brush-evoked pain, and brush width did not.
   In the capsaicin secondary zone only 3 of 9 controls had brush-evoked pain. Samuelsson, Leffler
   & Hansson 2011, *Scand J Pain* 2:85–92,
   [doi:10.1016/j.sjpain.2011.01.003](https://doi.org/10.1016/j.sjpain.2011.01.003). **Abstract
   only**, and the thesis summary was read only through a search excerpt (the KI archive returned
   403). du Jardin et al. 2013 used a 4.5 cm stroke that crossed the primary and secondary zones.
   They note that a 2 cm stroke could stay in one zone, but would probably give lower pain.
   Somedic Senselab brush no. 5: "width 15 mm". *Pain Res Manag* 18:6–10,
   [doi:10.1155/2013/142582](https://doi.org/10.1155/2013/142582)
   ([PMC3665431](https://pmc.ncbi.nlm.nih.gov/articles/PMC3665431/)). Read through a summary of
   the PMC page.
6. **Why sites rotate.**
   - The precedent the spec cites is for pinprick: "The pinprick stimulator was repositioned by
     1 cm after each stimulus to avoid sensitization of primary afferents". That was 10 stimuli
     at ISI 13–17 s, in the secondary zone, outside the flare. Scheuren et al. 2023, *J
     Neurophysiol* 130:436–445, [doi:10.1152/jn.00064.2023](https://doi.org/10.1152/jn.00064.2023).
   - The brush-evoked pain of secondary hyperalgesia is carried by Aβ low-threshold afferents into
     sensitised central neurons (Ziegler 1999 introduction; Liljencrantz 2014 discussion). So a
     brush stroke is not expected to sensitise nociceptors the way a pinprick can.
   - The reason to rotate a brush is different. "CTs … show fatigue (decreased responsiveness to
     repeated stimulation of the receptive field)" (Liljencrantz 2014, citing Nordin 1990, *J
     Physiol* 426:229–240, [doi:10.1113/jphysiol.1990.sp018135](https://doi.org/10.1113/jphysiol.1990.sp018135),
     not read). Repeated strokes also add up (item 5). The recovery time at a 13–17 s ISI was not
     found.
7. **No study found tests the number of brush sites, or rotation against a fixed site, for brush
   ratings.** The question is open in the literature: du Jardin 2013 state that data are "limited"
   on optimal stroke number, length, force, angle and speed.

## Options

- **A. Keep 8 sites in both zones.** In the primary zone the strokes must overlap or be shortened
  to about 1 cm. Overlap means re-brushing the same skin within a block while the software claims
  a different site. That is a false record (CLAUDE.md lesson 1).
- **B. One fixed site per zone, five strokes on the same line.** This matches DFNS (item 1) and
  Jürgens (item 2), which name no sub-sites. It is simple and gives the least spatial noise. The
  risk is CT fatigue and stroke summation on one line at about 15 s spacing (items 5 and 6), which
  could pull the five ratings in one direction within a block. It also departs from §8.3's "site
  rotates on every application".
- **C. Shorten the stroke to 1 cm, keep 8 sites.** Ziegler used 1 cm (item 3), so it is
  defensible. But a shorter stroke lowers brush pain (item 5) when the floor is already near zero
  (item 2, RB2). It also departs from the DFNS 2 cm and the approved instruction, and gives the
  experimenter two stroke lengths to remember.
- **D. Keep 2 cm; set sites per zone to what fits without overlap (recommended).**
  - **Primary: 4 sites.** A 2 × 2 grid: two parallel tracks along the 50 mm axis, each split into
    a proximal and a distal 2 cm segment. This needs a brush no wider than about 8 mm. Two tracks
    of a 15 mm Somedic brush do not fit across 25 mm, and the edge strokes would leave the zone.
  - **Secondary: 5 sites.** One per trial, so no skin is re-brushed within a block. Each stroke is
    laid tangentially, parallel to the thermode outline, beginning about 1 cm outside it, as in
    Ziegler's semicircle. The allodynic area is small and close to the primary zone (item 4), so a
    site placed further out will often test unsensitised skin and add zeros.
  - The cost is a per-zone site count in config and a different diagram for each zone.

## Recommendation

**Option D.**

- **Stroke:** one single stroke of about 2 cm in both zones, unchanged (DFNS; `apply_brush` already
  says it).
- **Primary zone: `n_sites` = 4**, laid out as a 2 × 2 grid of 2 cm segments along the long axis,
  kept off the zone's edge.
  - This assumes a brush of 8 mm or narrower.
  - **If the lab's goat-hair brush is wider than about 10 mm, use 2** (one central track, a
    proximal and a distal segment).
  - The brush width is a fact to confirm with S. It is not a safety limit.
- **Secondary zone: `n_sites` = 5.** Strokes run tangentially to the thermode outline, starting
  about 1 cm outside it. Spread them round the outline, and avoid the mapping paths' four
  directions where possible, so that brush strokes do not run over the lines just traced with the
  filament.
- **Rotation:** rotate on every application, as §8.3 says.
  - **Restart the sequence at site 1 at every block**, so that pre-S, post-S and post-I test the
    same sites in the same order. Primary is 1, 2, 3, 4, 1. Secondary is 1 to 5, each once.
  - The outcome is a change across time points, so the sites sampled should not differ between
    them. The same reasoning appears in SPEC §8.2, "Budget equally across time points".
  - The main session should check whether the current `SiteRotation` carries over between blocks.
    It is stateful (`tatp/pinprick.py` around line 486). This report did not trace how the brush
    uses it.
- This needs `brush.n_sites` split by zone (for example `n_sites_primary: 4`,
  `n_sites_secondary: 5`). It also needs the `primary_site_N` / `secondary_site_N` positions in the
  zone figure (open item 11) redrawn to match: strokes as short lines, not dots.

## What would change this

- **Bilaga 1 §3.6.3 naming a site count, stroke length or brush.** It overrides this report.
- **The lab brush's width.** Wider than about 10 mm gives 2 primary sites (above).
- **A pilot showing a within-block trend** (ratings rising or falling across strokes 1–5) at the
  re-used primary site. That would argue for fewer strokes, or a longer ISI, in the primary zone.
- **A pilot in which most secondary-zone ratings are 0 even after sensitisation.** If the flare or
  mapped border shows the sites lie outside the allodynic area, move them closer to the outline.
  If brush pain is absent everywhere (as in Samuelsson 2011, Jürgens 2014), the outcome is better
  treated as presence/absence. That is an analysis-plan question, not a site question.
- **The full text of Samuelsson 2011 or the Nordin 1990 CT-fatigue recovery time.** Either could
  show that same-site strokes 15 s apart are harmless (favouring B) or harmful (favouring more
  sites with shorter strokes, C).
