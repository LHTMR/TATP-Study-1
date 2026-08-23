# FOR_S — what needs you

Companion to `PROGRESS.md`. That file is the build handover; this one is the queue of things
the build cannot settle by itself.

**Everything here is non-blocking for the build.** Nothing on either list stops me writing
code. Each item is either carried as a marked placeholder that warns at startup
(`config/open_items.yaml`) or noted as an assumption. The build continues regardless — these
are the things that would otherwise get quietly guessed.

Two lists:

- **List A — things only you can supply.** I need a value, a wording or a decision from
  outside the repository. I will not invent these.
- **List B — things that need your attention.** No input to me required. Reviews, alignments
  between documents, and process that sits outside the software.

The **Gate** column says when the item stops being deferrable:

| Gate | Meaning |
|---|---|
| **Real participant** | The software will run, but a session collected without this is compromised or unusable. `blocks_use: true` in `config/open_items.yaml`. |
| **Piloting** | Needed to get useful answers out of the pilot, not to run it. |
| **Bring-up** | Belongs to the hardware bring-up session (`SPEC.md` §18.2). |
| **Analysis** | Not needed to collect data; needed before analysing it. |

---

## List A — things only you can supply

### A1. Participant-facing wording

The largest single item, and the one I have most deliberately not touched.

| # | What | Gate | Ref |
|---|---|---|---|
| A1.1 | **The participant screen text.** Welcome, standby, session-end, paused, emergency-stop, self-start, adjustment, comparison, preference and mapping instructions — in **both Swedish and English**. | Real participant | L4 |
| A1.2 | **English proportionality-training wording** for the pain, intensity and pleasantness scales. `SPEC.md` §10.6 supplies the Swedish only. **Now answerable** — Bilaga 1 supplies it ("a mark twice as far along the line indicates it is twice as painful", "twice as pleasant/intense"); transcribed in the draft below, needs only your yes. | Real participant | L4 |
| A1.3 | **Verification of the drafted Swedish VAS wordings** in `SPEC.md` §10.6 against the participant-facing ethics attachments. | Real participant | §20.12 |

**Why I stopped rather than drafted.** Participant-facing wording is bound by what the ethics
application says participants will be shown, and by the blinding constraints in `SPEC.md` §16 —
nothing may imply touch is expected to relieve pain, name the research environment, or
distinguish a condition. Writing plausible text would have produced something that reads fine
and is not what was approved. Every such string is currently `PLACEHOLDER…`, detected by
`Config.has_placeholder_text()`, and the experimenter screen carries an unmissable banner while
any remain.

**A draft now exists to react to:** `docs/participant_screen_text_draft.md`, written against
Bilaga 3a (approved participant vocabulary), Bilaga 1 and `article_summaries.md` §§IV and VIII.
It is a draft for you to mark up, not approved text, and it is deliberately **not** in the
config — the `PLACEHOLDER` gate and the startup banner are untouched.

**What I need:** the strings, in any form — a document, a table, a message. I will transcribe
them into `config/text/participant_{sv,en}.yaml`. Key names are already in place, so you can
work against that file directly if that is easier.

### A2. Safety and hardware limits

| # | What | Gate | Ref |
|---|---|---|---|
| A2.1 | **Software pressure ceiling.** §13 requires a hard ceiling below the 250 kPa hardware maximum but gives no number. **200 kPa is in place as a working value and is not an agreed limit.** Either give me a number or confirm 200 kPa stands. | Real participant | L1 |
| A2.2 | **Pressure rate limit.** Same situation. **60 kPa/s** is in place, chosen only to sit just above the 50 kPa/s top adjustment rate of §10.3. | Real participant | L2 |
| A2.3 | **Audio levels** — white noise, participant cue, experimenter alert, in dBFS. Placeholders now. Needs a meter at the headphones: the cue must be reliably audible over the noise, the experimenter alert must not be audible to the participant. | Real participant | L3 |
| A2.4 | **Screen indices and resolutions** for the lab PC. Null means "primary screen, windowed", which is right for development and wrong for a session. | Real participant | §20.9 |
| A2.5 | **Garment pressure resolution.** | Bring-up | §20.2 |
| A2.6 | **Inflation rate per channel.** Decides whether the 3 s static match transfers to the moving pattern, and sets pattern activation durations. | Bring-up | §20.3 |
| A2.7 | **Serial protocol for the proportional-valve controller.** The prototype carries a *bitmask* — one bit per channel — which cannot express a per-channel pressure. This is a protocol change to agree with whoever builds the controller, not just a driver change. `arduino_valves.py` cannot be written until it is settled. | Bring-up | §20.14 |

### A3. Measurements and study parameters

| # | What | Gate | Ref |
|---|---|---|---|
| A3.1 | **Measured filament forces and weighing date.** You do the weighing; the instruments module (launcher entry 2) writes them into `filaments.yaml`. Manufacturer forces deviate from measured by −19.75 % to +17.61 % non-systematically, so an unweighed set is recorded as such and flagged. | Real participant | §20.1 |
| A3.2 | **Real intervention patterns**, plus per-channel activation duration, overlap between consecutive activations, and the actual inter-channel spacing if it is not 1.5 cm. The three sweeps in `config/patterns/examples/` are provisional mockups. | Real participant | §20.5, §20.13 |
| A3.3 | **The session schedule grid** — block spacing, and whether the twelve rating blocks plus the rekindle define it. | Piloting | §20.4 |
| A3.4 | **Slope prior**, re-estimated from pilot data **pooled across participants, never per participant**. 51.6 VAS points per log₁₀ unit is a simulated starting value. | Piloting | §20.6 |
| A3.5 | **Expected pre-S → post-S offset** for the informed prior. −2.7 ladder steps from Scheuren et al.; confirm against pilot data. | Piloting | §20.7 |
| A3.6 | **Duration of one touch adjustment.** Decides whether the Protocol B time budget holds and which of schemes A/B/C is right. | Piloting | §20.8 |
| A3.7 | **A proper hyperalgesic-zone figure** to replace `assets/hyperalgesia_zones.svg`. Explicitly not blocking. | — | §20.11 |
| A3.8 | **Confirm the gram labels in `config/filaments.yaml` against the physical kit.** `label_g` is now the identifier for every filament (§8.1), so a wrong one names the wrong filament in a session. I transcribed the standard Semmes-Weinstein values rather than reading them off your kit. `tests/test_config_files.py` checks each label against `force_manual_mn` at 9.81 mN/g and all eleven agree to better than 1 %, so a typo is caught — but that verifies my arithmetic, not your kit. Eleven numbers to eyeball: 2, 4, 6, 8, 10, 15, 26, 60, 100, 180, 300. | Real participant | — |

### A4. Access

| # | What | Gate |
|---|---|---|
| A4.1 | **Is `LHTMR/ttpa_touch_the_pain_away` readable by me?** `SPEC.md` §5.2 names it as the source for the serial protocol. §12.4 already restates what I need — the bitmask control path and the `from_csv_matrix_vertical` parser defect — so I am not stuck. Say if you would rather I read it directly than work from the spec's summary. | Bring-up |

---

## List B — things that need your attention

Nothing here is an input to me. These are yours to decide, align or do.

### B1. Review what I wrote

| # | What |
|---|---|
| B1.1 | **The experimenter Swedish in `config/text/experimenter_sv.yaml`.** I wrote it from scratch — it is not participant-facing and not ethics-bound, so it needed no source, but it has had no native review. Roughly 110 lines. Session 6 added two blocks: `session:` (the identity strip) and `terms:` (the limb and zone words, so that values the software holds in English are not interpolated untranslated). The zone words are inflected to fit `"{region} zonen"` — *primära*, *sekundära*. |
| B1.2 | **The allocation design, before `config/allocation.csv` is generated and committed.** Condition order drawn from a pool holding each of the 6 permutations equally often. Starting limb alternates by participant *index*, which balances 21/20 exactly where random assignment would not. Codes `01`–`41`. Default seed `20260823`. Once sessions have been run against it, regenerating it re-allocates people, so this is worth a look now rather than later. |
| B1.3 | **`static_sham` = all five channels held on.** My assumption, so the sham matches the moving patterns in spatial extent and differs only in motion. A single-channel sham would differ in extent as well. Confirm at bring-up. |
| B1.4 | **`docs/DATA_SCHEMA.md`** — the column list for all eleven tables. It is *parsed* by the writer and the validator, so it is the real schema, not documentation of one. Worth reading once before data exists rather than after. |
| B1.5 | **One stated deviation from `SPEC.md` §12.1.** Its interface lists `play_pattern(pattern, params: dict)`. I implemented `play_pattern(pattern)` with no `params`, because every per-pattern parameter the spec names — row interval, channel ids, loop — lives in the pattern's sidecar YAML, and an empty dict nothing reads is the unused option `CLAUDE.md` forbids. Say if you intended `params` to carry something I have not anticipated. |
| B1.6 | **Three settled changes to `docs/SPEC.md` §8.1–8.2 and the `pinprick` schema**, all from your decisions of 23 Aug 2026 rather than mine, recorded so they do not live only in a chat log. **(a) Filaments are identified by their gram label** — `26`, not `5.46` — in `filaments.yaml`, on the experimenter screen and in the data. Forces became companion values. **(b) `intolerable` is now derived**, from a rating at the top of the pain scale, with the cap per site per time point and escalating to all sites once four sites are capped; enforcement lands with the ladder in Milestone 3. **(c) `force_applied_mn` falls back to the label force** while the set is unweighed, with the empty `force_measured_mn` as the marker — otherwise Protocol A cannot be piloted at all, and A3.4 asks you to re-estimate the slope prior from pilot data. Worth reading the new §8.1 and §8.2 to confirm I recorded them as you meant them. |

### B2. Align Bilaga 1 with what is implemented

Three places where the plan and the software have deliberately diverged. Each is already noted
in `SPEC.md`; none is a software change.

| # | What |
|---|---|
| B2.1 | **§3.7 preference selection.** The plan says preference "may also be selected" in the first session and used in all sessions. The software runs it in **every** session — which is what keeps its presence from signalling the condition to the experimenter, and yields a free within-participant measure of preference stability. Compatible with the permissive wording, but not what it describes. |
| B2.2 | **§3.9.1 pleasantness anchors.** The plan gives "unpleasant" to "very pleasant" — asymmetric. The implemented scale is **symmetric**, *mycket obehaglig* to *mycket behaglig*. |
| B2.3 | **The RSQ is a five-point Likert instrument** and is presented here on a VAS. The plan already says "adapted from", but the published item properties and reliability do not transfer directly to the VAS form. Worth one sentence. |

### B3. Decide before the pilot

| # | What |
|---|---|
| B3.1 | **The scheme B conditional check.** Scheme B was adopted *conditional on a pilot check*: run the full three anchors on the two channels expected to differ most and confirm the ratio between them is constant across levels. If it is not, fall back to scheme C. This check needs to be in the pilot protocol or it will not happen. |
| B3.2 | **Record enough repeats at one filament to estimate σ directly.** The simulated advantage of the whole Protocol A design rests on the s/σ ratio taken from Ng et al.'s Weber fraction. If real ratings are far noisier than that implies, the ranking of procedures narrows. |
| B3.3 | **The evenness question.** Whether the 3 s static match transfers to the moving pattern is deferred to piloting and answered by asking the participant. The software supports the check and a rebalance path; someone has to actually ask. |

### B4. Analysis plan

| # | What |
|---|---|
| B4.1 | **State in advance what happens to `out_of_range` sessions.** Amir et al. had 25.7 % of participants ineligible on range criteria with roughly four times as many stimulus levels as this ladder has, so expect this to fire in a meaningful fraction of sessions. It is not an edge case, and deciding after seeing the data is worse than deciding now. |
| B4.2 | **The fixed slope is an assumption about the participant.** If sensitisation genuinely steepens the slope, the same prior at pre-S and post-S is wrong in a *systematic* direction — worse than random error for a DV compared across time points. Every force/rating pair is stored, so a pooled slope can be estimated per time point in analysis. Worth planning for. |
| B4.3 | **Calibration agency may compress the condition-2 effect.** Calibration by adjustment gives the participant control over the stimulus in every condition, and Study 1's condition 2 is defined by exactly that contrast. Constant across conditions so it does not confound, but it may raise pleasantness across the board. |
| B4.4 | **Blinding is a managed limitation, not a property.** An experimenter running many sessions may infer the structure. The software's obligation is narrower and absolute — never to be the thing that reveals the condition. The limitation belongs in the write-up. |
| B4.5 | **A ceiling pain rating is a censored observation.** Now that the top of the scale is the proxy for intolerable (§8.2), a rating of 100 means the participant had no headroom, so their true response may be higher. Fitting it as a plain point biases the fixed-slope estimate. It will nearly always land on a `search` trial, since measurement sits at the crossing filament and the two below it near VAS 40, so it should rarely enter the fit — but the analysis plan should say what happens when it does. |

### B5. Process and environment

| # | What |
|---|---|
| B5.1 | **`git push` is denied to me — you push.** Nothing is on the remote yet. |
| B5.2 | **`environment.yml` changed:** `sounddevice` → `python-sounddevice`, the conda-forge package name. The original spelling does not resolve on any channel and `conda env create` failed outright. Verify it installs on the **Windows lab PC**, which is the machine that matters. The import name in Python is unchanged. |
| B5.3 | **One permission hole I did not close, now stated more honestly than before.** `conda run … python` can execute anything and the Makefile needs it. It is narrowed to the four forms the Makefile actually uses rather than allowed wholesale. Session 3 widened the `tools/` form from a dead prefix to `Bash(… python tools/*)` — any script in `tools/`, any arguments. That is not a real loosening: a per-script rule was never a security boundary either, because I write the scripts. What a per-script rule did buy was blocking arguments, and `make_allocation.py` takes `--out`, which writes anywhere. That protection moved into `.claude/hooks/check_bash.py`, which now resolves **every** path token in a command — relative ones included — and refuses anything outside the repository. The remaining exposure is unchanged and unclosable while the Makefile needs `conda run`: I can put arbitrary code in a `tools/` script. The tripwire is that a *new* filename is visible in the diff, not that it prompts. |
| B5.4 | **Manual data transfer to the LiU secure server** (§14.1) is outside the software. The process needs to exist and belongs in `SOP.md` when I write it. |
| B5.5 | ~~Decide which environment the build runs in.~~ **Resolved, session 4.** Installing the CLI (B5.6) put `claude` on `PATH`; the session now honours `.claude/settings.json`'s `permissions.allow` block — confirmed with a clean, unprompted `git add -A`. No further action. |
| B5.6 | ~~`claude` is not on `PATH`.~~ **Resolved, session 4.** CLI installed properly; `claude` now resolves on `PATH`, which is what fixed B5.5. No further action. |

---

## What I do meanwhile

None of the above stops the build. Placeholders warn at startup, assumptions are recorded in
`PROGRESS.md`, and `config/open_items.yaml` is the machine-checked list — an item is resolved
when its `resolved_when:` config path stops being null, so this document and the software
cannot silently disagree about what is outstanding.

The order of work is in `PROGRESS.md` under "Next steps".
