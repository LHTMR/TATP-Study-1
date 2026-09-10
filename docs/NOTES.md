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

## 5. The UI review, 26 Aug 2026

`docs/UI_PRINCIPLES.md` was written first, on the `ui-review` branch, so the review had a stated
standard rather than a reviewer's taste. Every screen state was read as a rendered PNG in both
languages, graded validity / safety / usability / polish, and fixed in one pass.

| # | What |
|---|---|
| N5.1 | **Stacked anchor labels were relabelling the scale.** On `pain` and `intensity`, in both languages, a label that would collide dropped to a second row with nothing tying it to its percentage. English `intensity` row 0 then read "no sensation at all … just uncomfortable" — a complete scale with the wrong top anchor, on the scale the whole touch calibration is rated against. Fixed by ticking every labelled anchor, which `SPEC.md` §10.2 permits ("no tick marks *beyond* the labelled anchors"), and running the tick down to the label's own row as a leader. Bilaga 1 fixes the anchor wordings and positions, so shortening a label was never available. `tests/test_vas.py` now asserts every anchor's tick sits at its own percentage. |
| N5.2 | **The experimenter screen reflowed when a warning appeared.** Banners were ordinary layout items, so the phase and the instruction slid down at the moment something went wrong. The banner region is now reserved whether occupied or not, with a test that both banners fit inside it — a wording change that would overflow fails the suite rather than silently clipping a `SPEC.md` §12.4 warning. |
| N5.3 | **"Frånkopplad" was typeset exactly like "Ansluten".** A disconnected garment was indistinguishable at a glance from a working one. Connected is now quiet secondary text and disconnected is red and bold. The two banners were also identically red despite demanding different responses, and are now red and amber. |
| N5.4 | **The screen was a full-brightness light page** sharing a dim room with a near-black participant screen. Now dark, with one four-step type scale, and the instruction — what to do now — as the largest element rather than the always-on monofilament technique blurb. |
| N5.5 | **Participant text moved between screens.** Message screens centred vertically while the VAS question sat near the top, so the first line to read shifted on every one of roughly 150 rating cycles. Both now top-align at the same fraction. The emergency-stop screen is bold, so it is not mistakable for a rest screen — weight rather than colour, because an alarming screen is the wrong thing to show someone who has just pressed the button. |
| N5.6 | **`participant_en.yaml` welcome had a stray line break** ("… does not see your / answers."), from hard newlines in the block scalar colliding with word wrap. Swedish was unaffected — which is the case for reviewing the two languages as a pair. Wording unchanged; only the line breaking. |
| N5.8 | **Ticks on a VAS pull responses toward themselves.** Measured, not assumed: marking a VAS cut mean absolute error from 3.02 to 0.82 units and error SD from 0.87 to 0.25 (*Behavior Research Methods* 2023), because respondents place marks near the marks. On these scales the ticked positions are the anchors Bilaga 1 fixes — the categorical landmarks participants are trained to use — so the pull is wanted rather than a bias to remove. It is still a property of the primary outcome's distribution and should be stated in the write-up rather than found in the data. It is also the standing reason never to tick anywhere else on the line. Note that classical guidance (FDA PRO, and Reed & Van Nostran 2014) says a VAS should carry no intermediate descriptors at all — Bilaga 1's 10 % and 10/90 % anchors are already a deliberate, cited departure from it, so this is a settled deviation and not something a review reopens. |
| N5.9 | **No published guidance exists on VAS anchor-label overlap specifically.** Searched: the pain literature, the paper-to-electronic VAS migration literature, and the psychophysics scale-design literature. The applicable guidance is from data visualisation, where the problem is identical and settled — stagger onto alternating rows, and use leader lines to tie a displaced label to its position. Rotated or angled labels are consistently advised against, being measurably slower to read. The current design is therefore the endorsed approach, and remaining dissatisfaction with it is about execution, not method. |
| N5.10 | **The comparison screen becomes a direct-press choice, decided 26 Aug 2026.** Rendered buttons matching the physical remote replace the sentence describing them, the press itself is the response with no confirm step, the chosen button is shown back for ~0.5 s, and a ~0.5 s blank separates trials. Both durations are config and pilot-tunable — the requirement is perceptual (long enough to notice, short enough not to feel laggy), so they are tuned by looking, not derived. This changes `SPEC.md` and `DATA_SCHEMA.md`, not just the UI: a comparison response no longer has a confirm event, and a participant can no longer revise a choice. |
| N5.11 | **The drawn buttons are tied to the physical device, so a relabelling propagates.** The remote's two large buttons are chevrons and the two small ones carry a play icon and a blank-screen icon. S may put new labels on the lower two. Whatever is physically on a button is what the screen must draw (`UI_PRINCIPLES.md` 5.9) — so the confirm symbol used across the participant screens is pending that decision rather than settled. |
| N5.14 | **The participant will rehearse the emergency stop once per session, with the garment running** (S, 26 Aug 2026; `SPEC.md` §10.9). Worth flagging for Bilaga 1: §3.10 says participants are *told* that pressing the stop will not disturb the experiment, and the rehearsal goes past telling — they press it and watch the resume. That strengthens the consent position rather than departing from it, but the plan describes a briefing where the procedure is now a demonstration, so the sentence is worth aligning. The participant-facing wording is practical instruction about a button, the same category as `audio_setup`, and S approved it directly on 10 Sep 2026 after removing a drafted line, "You never need a reason to use it", which went past what Bilaga 1 §3.10 promises. |
| N5.12 | **`audio_setup.still_audible` has the same shape as `choices.comparison` and should move into `choices` when `audio.py` is built.** Both are a question with a left and a right option label, both are answered by the matching large button, and `SPEC.md` §10.8 now covers both. It was left where it is rather than moved as part of a UI item, because relocating approved wording is a change S reads in the config diff and it should happen in the commit that gives it a consumer. |
| N5.13 | **`equal` dropped from `touchcal_compare.judgement`, S's decision 26 Aug 2026.** It had no route through the interface and never had one: the screen offers two buttons and asks which felt stronger, and since the direct-press change there is not even a confirm step where a third option could have hidden. The alternative was a third option, which would have needed approved wording and a button the remote does not have. Dropping it also puts the column back in step with the analysis — the comparison document sizes the equalisation check as a **2AFC** (§6, the d′ derivation), and in a forced choice between two a tie is a missing response rather than a response category. The equalisation procedure does not exist yet, so nothing had to be rewritten; if it had, this would have been a live analysis question rather than a tidy-up. |
| N5.7 | **The reference screenshots are still unapproved.** None had ever been approved, so `make shots` compares nothing and the review could change screens freely. `make shots ARGS="--approve-all"` is S's to run once the new screens are accepted. |
