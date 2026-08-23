# NOTES — things logged, not waiting on anyone

Observations that should not be lost but are nobody's blocker: deliberate deviations from
Bilaga 1, checks that must reach the pilot protocol, questions the analysis plan should answer
before data exists, and process that sits outside the software.

**This file is not a queue.** `FOR_S.md` is the queue, and it holds only what S must supply for
the build to move. Nothing here needs an answer to keep building; each entry exists so that when
S reviews, the thing they are looking at has a written history. Build state and decisions taken
are in `PROGRESS.md`; the specification is `docs/SPEC.md`.

---

## 1. Where the implementation diverges from Bilaga 1

Deliberate, each already noted in `SPEC.md`, none a software change.

| # | What |
|---|---|
| N1.1 | **§3.7 preference selection.** The plan says preference "may also be selected" in the first session and used in all sessions. The software runs it in **every** session — which keeps its presence from signalling the condition to the experimenter, and yields a free within-participant measure of preference stability. Compatible with the permissive wording, but not what it describes. |
| N1.2 | **§3.9.1 pleasantness anchors.** The plan gives "unpleasant" to "very pleasant" — asymmetric. The implemented scale is **symmetric**, *mycket obehaglig* to *mycket behaglig*. |
| N1.3 | **The RSQ is a five-point Likert instrument** presented here on a VAS. The plan says "adapted from", but the published item properties and reliability do not transfer directly to the VAS form. Worth one sentence in the write-up. |

## 2. Checks that must be in the pilot protocol

The software supports each; someone has to actually run it.

| # | What |
|---|---|
| N2.1 | **The scheme B conditional check.** Scheme B was adopted *conditional on a pilot check*: run the full three anchors on the two channels expected to differ most and confirm the ratio between them is constant across levels. If it is not, fall back to scheme C. |
| N2.2 | **Record enough repeats at one filament to estimate σ directly.** The simulated advantage of the Protocol A design rests on the s/σ ratio taken from Ng et al.'s Weber fraction. If real ratings are noisier, the ranking of procedures narrows. |
| N2.3 | **The evenness question.** Whether the 3 s static match transfers to the moving pattern is answered by asking the participant. The software supports the check and a rebalance path. |
| N2.4 | **Does the fit preview stay on for real sessions?** `SPEC.md` §11.1. Off by default and built for piloting. It shows the experimenter the participant's ratings, which Bilaga 1 §3.3 and the welcome screen both say does not happen — so keeping it on means changing those, not just the config. A test fails if the flag is flipped without it, and `fit_preview_enabled` in the session file tells analysis which sessions were affected. |
| N2.6 | **Every participant feels the CT-targeted pattern in setup, before calibration.** The masking check runs it at low amplitude so the valve switching is audible (`SPEC.md` §10.7). It is the same fixed pattern in every session, so it cannot signal the condition — but it does mean nobody reaches their own condition naive to that pattern, and participants in the CT-targeted condition have felt theirs once before. Constant across conditions, so not a confound; worth a sentence if familiarity with the moving pattern is ever at issue. |
| N2.8 | **Earplugs attenuate the participant cue as well as the garment.** If earplugs are fitted (`SPEC.md` §10.7 step 5), the warning cue and every other sound reaching the participant are quieter too. The cue is set relative to the noise, so it keeps its margin *over the noise* — but both are now heard through a plug, and nobody has checked that the cue is still comfortably detectable that way. Confirm with the first pilot participant who needs earplugs. `earplugs_used` marks those sessions. |
| N2.7 | **Check that the masking actually holds during a block, not only in setup.** The check is done once, on a low-amplitude pattern. Intervention blocks run at calibrated pressures, which are higher and may well be louder. `masking_confirmed` records the setup answer, not the session-long truth. Ask a pilot participant at the end whether they could hear the garment during the blocks. |
| N2.5 | **Minimum exploration is recorded, not enforced.** The comparison document §7.3 asks for a minimum total travel before a confirm is accepted (`min_exploration_kpa`, 20 kPa). `min_exploration_met` is written on every `touchcal_adjust` row, but a short confirm is still accepted: refusing one means telling the participant why, and there is no approved wording for that — inventing one would be participant-facing text written outside the ethics attachments (`SPEC.md` §10.4). If it should bite rather than be flagged, it needs a sentence in the participant text first. |

## 3. For the analysis plan, before data exists

| # | What |
|---|---|
| N3.1 | **State in advance what happens to `out_of_range` sessions.** Amir et al. had 25.7 % of participants ineligible on range criteria with roughly four times as many stimulus levels as this ladder has, so expect this in a meaningful fraction of sessions. Deciding after seeing the data is worse than deciding now. |
| N3.2 | **The fixed slope is an assumption about the participant.** If sensitisation steepens the slope, the same prior at pre-S and post-S is wrong in a *systematic* direction — worse than random error for a DV compared across time points. Every force/rating pair is stored, so a pooled slope can be estimated per time point in analysis. |
| N3.3 | **Calibration agency may compress the condition-2 effect.** Calibration by adjustment gives the participant control over the stimulus in every condition, and Study 1's condition 2 is defined by exactly that contrast. Constant across conditions so it does not confound, but it may raise pleasantness across the board. |
| N3.4 | **Blinding is a managed limitation, not a property.** An experimenter running many sessions may infer the structure. The software's obligation is narrower and absolute — never to be the thing that reveals the condition. The limitation belongs in the write-up. |
| N3.5 | **A ceiling pain rating is a censored observation.** With the top of the scale as the proxy for intolerable (§8.2), a rating of 100 means the participant had no headroom, so their true response may be higher. Fitting it as a plain point biases the fixed-slope estimate. It should rarely enter the fit — measurement sits at the crossing filament and the two below it near VAS 40 — but the plan should say what happens when it does. |

| N3.6 | **A block's planned offset is recorded as prose, not as a column.** `SPEC.md` §7.4 asks for the planned offset, actual start and actual end of every block, and `DATA_SCHEMA.md` has no `blocks` table — so they go in `log.detail`, as `"pinprick; planned 50 min, started 51.20 min, +1.20 min against plan"`. The actual start and end are recoverable exactly from the row's own `t_session_s`, but the *planned* offset can only be recovered by parsing that sentence, or by regenerating the grid from the `schedule_sha256` in the session file. If drift against plan turns out to be an analysis variable rather than a monitoring aid, it needs a `blocks` table rather than a regex. |

## 4. Process, outside the software

| # | What |
|---|---|
| N4.1 | **Manual data transfer to the LiU secure server** (`SPEC.md` §14.1) is outside the software. The process needs to exist and belongs in `SOP.md` when it is written. |
| N4.2 | **Parallel Claude sessions get a branch.** Two agents sharing one working tree on `main` cannot tell whose uncommitted change is whose; this already caused one mis-attributed commit (`PROGRESS.md` decision 22). |
