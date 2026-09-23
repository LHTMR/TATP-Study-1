# Research reports

One report per decision the spec does not settle, each written by the `decision-research`
agent (`.claude/agents/decision-research.md`) before the decision was taken. The decision itself
is recorded in `docs/LOG.md` §7, which links back here. A report explains what the evidence
said at the time. It does not make the decision binding — S can overturn any of them.

Numbers are never reused.

| # | Question | Confidence | Decision |
|---|---|---|---|
| [R30](R30-touchcal-stage1-gate.md) | Numeric criteria for a "flat", "non-monotonic" or "poor residuals" stage-1 touch-calibration fit (SPEC §9 step 2) | low (values), medium (choice of statistics) | Flat: fitted span b·log10(Pmax/Pmin) < 40 VAS; non-monotonic: Spearman ρ < 0.56 (n = 10); poor residuals: residual SD > 25 VAS; R² stored, not gated |
| [R32](R32-touchcal-estimation-timing.md) | Touch-calibration estimation run (SPEC §9 step 2): hold before VAS, stimulus during rating, off-interval, amplitude spacing, catch-trial count | medium (off-interval low) | 3 s hold from command; stimulus on until confirm, 12 s rating timeout; off 8–12 s jittered; 10 log-even amplitudes inclusive of bracket; 2 catch trials added (12 total) |

## To fetch

Papers a report could read only as an abstract. **Nothing waits on these.** Each decision was
taken without the full text. If S drops a PDF into `docs/research/sources/` (gitignored, because
papers are copyrighted), a later session re-reads it and updates the report that cited it.

| DOI | Title | Wanted by |
|---|---|---|
| 10.1113/jphysiol.1980.sp013160 | Knibestöl & Vallbo 1980, Intensity of sensation related to activity of slowly adapting mechanoreceptive units in the human hand | R32 |
| 10.1152/jn.1999.81.6.2753 | Vallbo et al. 1999, Unmyelinated afferents constitute a second system coding tactile stimuli of the human hairy skin | R32 |
| 10.1016/j.pain.2006.01.041 | Rolke et al. 2006, QST in the DFNS: standardized protocol and reference values | R32, R30 (confirm MPS carries no fit-quality criterion) |
| 10.1016/j.neuroscience.2020.07.050 | Case et al. 2021, Pleasant deep pressure: expanding the social touch hypothesis (open access as PMC7865002, fetch blocked this session) | R32 |
| 10.1016/j.pain.2013.12.015 | Khoshnejad et al. 2014, Remembering the dynamic changes in pain intensity and unpleasantness | R32 |
| (no DOI verified) | Nafe & Wagoner 1941, The nature of pressure adaptation, J Gen Psychol 25 | R32 |
| 10.1111/psyp.14505 | Świder et al. 2024, How to make calibration less painful (exact R² and gradient-convergence rejection rules; medRxiv PDF 10.1101/2022.10.03.22280662 could not be extracted) | R30 |
