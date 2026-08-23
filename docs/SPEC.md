# SPEC — TATP Study 1 experiment control software

Version 1.4, 22 August 2026. Author: Sarah McIntyre, with Claude.
Repository: `TATP-Study-1` (LHTMR), at `~/Documents/GitHub/TATP-Study-1`.
Written to be executed by a fresh Claude Code session. Read this file, then
`docs/calibration_methods_comparison.md`, before writing any code.

**TATP = Touch Away The Pain.** Not "ttpa". The Python package is `tatp/`.

Changes from 1.0: PySide6 replaces PsychoPy (§3, §4); separate data file per observational
unit (§14); experimenter is blinded to condition (§11, §16); a pattern design module (§12);
instrument-and-environment module (§8.1); independent experimenter and participant languages
(§10.4); adversarial experimenters (§17.5).
Changes in 1.2: the pattern authoring format stays the tick-grid CSV with a per-pattern row
interval — v1.1 wrongly treated the 100 ms default as fixed (§12.2); looping and overlap
specified; preference selection runs every session (§9, §16); Swedish VAS wordings added as an
open item (§20).
Changes in 1.3: conda instead of a bare virtualenv (§3); `capabilities()` on the garment
interface and three drivers rather than two (§12.1); piloting against the current prototype
(§12.4); Swedish VAS wordings drafted (§10.6); the zone diagram placeholder now exists (§11).
Changes in 1.4: Swedish settled and the RSQ items retranslated from the German original, with
two deviations from Bilaga 1 recorded (§10.6); `capabilities()` clarified as a driver
declaration rather than a device query (§12.1); what the prototype's control path actually does,
and a silent-failure defect in its pattern parser (§12.4); the valve controller's serial
protocol added as an open item (§20).

---

## 0. How to use this document

This spec is self-contained. Everything needed is here or in the files named in §1.3. Where a
value is not yet known it appears in §20 as an open item and must be a configuration parameter
with a clearly-marked placeholder — **never a guessed constant in the code.**

If a required input is missing or contradictory, **stop and ask.** Do not infer a substitute,
do not use synthetic or fallback data, do not proceed with partial results.

Build order is in §18. Do not build the whole system at once.

---

## 1. Purpose and scope

### 1.1 What this software is

An application that runs a single experimental session of TATP Study 1: it guides the
experimenter and the participant through the session, presents rating scales, runs two
adaptive calibration procedures, commands the actuating garment, and records everything to
disk.

### 1.2 Out of scope

- **The thermode.** The TCS II (QST.Lab) is operated separately. The software times the
  sensitisation and rekindling phases and prompts the experimenter, but sends nothing to the
  thermode and receives nothing from it.
- **Questionnaires.** PCS, ASI, ASQ, STQ, AQ, the background form and the per-visit session
  form are all in REDCap. The software records only that the session form was completed, plus
  the identifiers needed to link records.
- **Analysis.** No statistics, no plots, no aggregation beyond what the session needs. The
  §3.11 sensitisation-failure criterion is applied in analysis, not here.
- **Studies 2 and 3.** Build for Study 1. Structure the code so those are a new configuration
  plus one new garment driver, not a rewrite.
- **Recruitment, scheduling, consent.**

### 1.3 Source documents

- `Bilaga1_Forskningsplan_V2.docx` — the authoritative research plan. All scientific and
  design content comes from V2 only. **It is deliberately not copied into this repository**:
  it is a live document that would diverge, and it is an ethics submission that should not
  become public if this repository does. Everything the build needs from it is either restated
  in this spec or must be transcribed into `config/text/` (§20 item 12).
- `docs/calibration_methods_comparison.md` (rev. 8) — the analysis behind both calibration
  procedures, with `docs/calibration_sim.py`. **Read it. Do not re-derive the design.**

---

## 2. The session at a glance

One session, about three hours, on one arm.

| Phase | What happens | Software role |
|---|---|---|
| Setup | Session details, garment fitted | Collect and validate session metadata |
| Touch calibration (TC) | Garment calibration, VAS familiarisation | Protocol B (§9) |
| Pre-sensitisation | VAS training, baseline pain measures, SH area mapping | Long protocol (§8.2), mapping (§8.4) |
| Heat sensitisation | Thermode 50 °C, 2 min | Time and prompt only |
| Capsaicin | 0.075 % capsaicin, 30 min | Time and prompt only |
| Post-sensitisation | Pain measures, SH area mapping | Long protocol, mapping |
| Intervention | 120 min; 6 pinprick and 6 touch-rating blocks alternating; rekindle at t+60 | Schedule, short protocols, garment |
| Post-intervention | Pain measures, SH area mapping | Long protocol, mapping |

Three touch conditions, one per session, in a pre-generated counterbalanced order. Target limb
alternates between visits.

---

## 3. Platform

**PySide6 (Qt) for the whole application. PsychoPy is not used.**

Nothing in this experiment needs frame-locked visual presentation, which is what PsychoPy is
built for. What is needed is a real application interface — a zone diagram, a connectivity
panel, buttons, a notes field — and that is what Qt provides. Two further consequences make
this the right choice, and both are load-bearing for §17:

- Qt runs headless under `QT_QPA_PLATFORM=offscreen`, so the end-to-end validator and the
  screenshot mode need no display at all.
- `QWidget.grab()` renders deterministically, so pixel-diff regression is reliable rather than
  dependent on GPU and driver.

Timing is handled with `time.perf_counter()` and Qt timers. Sound with `sounddevice` (white
noise is generated, not a file). Randomisation with `numpy.random.Generator`, seeded and
recorded.

Other environment facts:

- **One Windows lab PC, two displays.** Participant window fullscreen on the display behind
  the curtain; experimenter window on the lab display. One process, one clock.
- **Conda environment `tatp-study-1`, declared in `environment.yml`.** Add dependencies by
  editing that file and running `conda env update -f environment.yml --prune`, never with an
  ad-hoc `conda install` or `pip install` — an ad-hoc install is invisible in the diff and will
  not exist on the lab PC. Makefile targets run through `conda run -n tatp-study-1`. Record the
  resolved package versions in each session file.
- **Participant response device: Logitech R400 presenter.** It emits only `pageup`,
  `pagedown`, `f5`, and — from the play button — `escape` **and** `period`.
- **Garment:** up to 250 kPa, proportional valves, **five independently controlled channels**,
  serial from an Arduino. Existing driver:
  <https://github.com/LHTMR/ttpa_touch_the_pain_away>. Pressure resolution unknown (§20).
- **Monofilaments:** Aesthesio (DanMic) Semmes–Weinstein, the set used in Ng et al. (2024).

---

## 4. Architecture

```
TATP-Study-1/
├── run_session.py              entry point → launcher (§4.1)
├── config/
│   ├── study1.yaml             design parameters
│   ├── hardware.yaml           ports, pressure limits, screens, audio, adjustment rates
│   ├── schedule.yaml           session timeline (§7)
│   ├── filaments.yaml          measured filament forces (§8.1)
│   ├── patterns/               garment pattern definitions (§12.2)
│   └── text/
│       ├── participant_sv.yaml   every participant-facing string
│       ├── participant_en.yaml
│       ├── experimenter_sv.yaml
│       └── experimenter_en.yaml
├── tatp/
│   ├── launcher.py             startup screen and module selection (§4.1)
│   ├── session.py              session state machine, clock, resume
│   ├── schedule.py             generation, override, validation, preview
│   ├── allocation.py           reads the counterbalancing file
│   ├── datafiles.py            all disk writes (§14)
│   ├── ui/
│   │   ├── participant.py      fullscreen participant window
│   │   ├── experimenter.py     experimenter window (§11)
│   │   ├── vas.py              the VAS widget
│   │   └── widgets.py          shared components
│   ├── responder.py            R400 input handling
│   ├── audio.py                white noise and alert tones
│   ├── garment/
│   │   ├── base.py             GarmentController interface (§12.1)
│   │   ├── arduino.py          real driver
│   │   ├── mock.py             mock driver
│   │   └── patterns.py         pattern loading and playback
│   ├── pinprick.py             Protocol A (§8)
│   ├── touchcal.py             Protocol B (§9)
│   ├── instruments.py          filament weighing, temperature, humidity (§8.1)
│   └── screenshots.py          screenshot mode and manifest (§17.4)
├── tools/
│   ├── preview_schedule.py
│   ├── validate_session.py     the end-to-end validator (§17.3)
│   ├── make_allocation.py
│   ├── design_pattern.py       pattern designer (§12.2)
│   └── check.py                the gate (§17.1)
├── tests/
├── sim/
│   ├── responders.py           virtual participants (§17.5)
│   └── experimenters.py        virtual experimenters (§17.5)
├── assets/
│   └── hyperalgesia_zones.svg   experimenter zone diagram (§11)
├── docs/                       SPEC.md, DATA_SCHEMA.md, the calibration documents
├── screenshots/
│   ├── reference/              approved images, committed
│   └── manifest.yaml
├── data/                       gitignored (§14.1)
├── .claude/                    settings.json and hooks/check_bash.py
├── CLAUDE.md
├── README.md  SOP.md  HARDWARE_BRINGUP.md
├── Makefile
├── environment.yml
└── PROGRESS.md
```

### 4.1 Launcher

`run_session.py` opens a launcher offering four entries, so the auxiliary tools are reachable
without the command line:

1. **Run a session** — the experiment.
2. **Instruments and environment** — filament weighing, temperature, humidity (§8.1).
3. **Design a pattern** — the garment pattern designer (§12.2).
4. **Preview schedule** — the timeline and its warnings (§7.2).

### 4.2 The rule about literals

**No timings, forces, pressures, thresholds, rates or participant-facing strings in `.py`
files.** They live in `config/`. A numeric literal in `tatp/pinprick.py` or `tatp/touchcal.py`
should be an array index or a unit conversion, nothing else. A test greps for violations.

---

## 5. Style and conventions

### 5.1 Naming

PEP 8. `snake_case` for both functions and variables, `CapWords` for classes,
`UPPER_SNAKE_CASE` for constants. No separate convention distinguishing functions from
variables — the distinction is not worth the inconsistency it invites, and PEP 8 does not make
it.

### 5.2 What to take from the exemplars, and what not to

The exemplars are PsychoPy applications and this is a Qt application, so take **structure and
data conventions, not display code**.

1. **<https://github.com/SDAMcIntyre/Touch-Comm-ASD>** — primary exemplar. Read `touchcomm.py`.
   Take: the `DataFileCollection` pattern of open-append-close on every write; external
   bilingual text files; the separation of an experiment script from a reusable module; the
   `# -- SECTION --` / `# ----` block comments. Do **not** take its display classes.
2. **<https://github.com/SDAMcIntyre/Expt_MonofilamentDiscrimination>** — read
   `Experiment_PainDiscrimination.py` for how the experimenter is prompted and cued, and for
   the data-file naming convention.
3. **<https://github.com/LHTMR/ttpa_touch_the_pain_away>** — for the serial protocol only. Its
   Python is work-in-progress; take no structural conventions from it.

Deliberate departures, all decided: Qt instead of PsychoPy; configuration files instead of an
in-script dict and dialog; `snake_case` instead of camelCase; `_session.csv` instead of
`_info.csv`, because it holds provenance as well as settings.

### 5.3 Other

- Comments explain **why**, not what.
- Minimal code. No abstraction used once. No config option nothing reads.
- **Fail fast.** No broad `try`/`except`; let exceptions propagate. The sole exception is the
  data-write path, which must never lose an already-collected trial.
- Assert at every stage boundary.
- Units in names: `isi_min_s`, `pressure_max_kpa`, `force_mn`.
- Licence GPL-3.0, matching the exemplars.

---

## 6. Configuration

Validated on load. Missing key, wrong type, out-of-range value, or a referenced file that does
not exist → stop with a message naming the file, the key and the problem. **Never fall back to
a default for a value that was supposed to be supplied.**

The launch dialog collects only: participant code, session number, experimenter initials,
participant language, experimenter language, data folder, pattern folder. Everything else
comes from config.

---

## 7. The session schedule

### 7.1 Representation

**Generated from parameters, then overridable per block.** `schedule.yaml` has a `generate:`
section (numbers of pinprick and touch blocks, intervention duration, rekindle offset,
capsaicin duration) producing an evenly spaced grid, and an `overrides:` section replacing the
offset or type of any individual block. The generated grid alternates pinprick and touch
blocks, evenly spaced, never back-to-back.

The grid is **not settled and will change during piloting** (§20). This is why it is data.

### 7.2 Preview

`tools/preview_schedule.py`, also reachable from the launcher, prints the timeline as a table —
block index, type, planned offset, planned wall-clock time, expected duration — and the total
session length. No hardware, no session started.

### 7.3 Validation: warn, do not block

Checks for overlapping blocks; a block inside the capsaicin window; a block overlapping the
rekindle; unequal spacing between same-type blocks; a session over a configured maximum. Each
prints a clear warning naming the block and the rule. **None prevents the schedule running** —
piloting will legitimately want irregular schedules. This is the one deliberate exception to
fail-fast, and it is a scheduling decision rather than error handling.

### 7.4 Clock and drift

The software **times phases and displays countdowns; the experimenter launches each block.**
Session t=0 is the start of heat sensitisation. Record planned offset, actual start and actual
end for every block. Alert the experimenter audibly when a block becomes due and again when
overdue by a configured margin. No block is ever skipped automatically.

The garment is **deactivated for the rekindle** and reactivated afterwards (Bilaga 1 §3.5).
Log both transitions.

---

## 8. Protocol A — pinprick

### 8.1 Filaments, and the instruments module

**Filaments are identified by the gram label printed on them** — `26`, not `5.46`. Settled
23 Aug 2026: that is what an experimenter reads off the kit under time pressure, so it is the
identifier in `filaments.yaml`, on the experimenter screen and in the data files. Everything
else about a filament — the Semmes-Weinstein size, the nominal force, the measured force — is a
companion value looked up from the label.

`filaments.yaml` lists the filaments held: gram label, Aesthesio size, nominal force, **measured
force in mN**, and the weighing date. The measured value is what the code uses **where there is
one**; where the set is unweighed the estimator falls back to the label force, and the empty
`force_measured_mn` in each row is what marks a row fitted that way. Piloting depends on this:
the slope prior is re-estimated from pilot data (§20 item 6), which cannot happen if no force is
recorded at all. Manufacturer forces deviate from measured by −19.75 % to +17.61 %
non-systematically (Berquin et al. 2010), which is why the fallback is marked rather than
silent.

Reference values from the Aesthesio manual, mN, for the range Ng et al. (2024) used:

| Size | 5.07 | 5.18 | 5.46 | 5.88 | 6.10 | 6.45 | 6.65 |
|---|---|---|---|---|---|---|---|
| Manual force | 98.0 | 147 | 255 | 588 | 980 | 1760 | 2940 |
| Nominal label | 100 | 150 | 260 | 600 | 1000 | 1800 | 3000 |

**Bilaga 1 §3.6.1's "260 mN" filament is the 5.46, actual force 255 mN.** The ladder is not
limited to this range — the kit continues down through 78.4, 58.8, 39.2, 19.6 mN, and the
post-S target will sometimes fall below 100 mN. Config lists whatever is held.

**Instruments and environment module** (launcher entry 2, `tatp/instruments.py`): enter
precision-balance measurements for each filament, which writes them with the date into
`filaments.yaml`; and enter room temperature and relative humidity, which are written to the
session file. **Temperature and humidity are optional** — a session runs without them, with
the field recorded as missing.

No humidity correction is applied. This lab runs below 30 % RH, outside the 40–67 % range
Berquin tested, so his correction would be an extrapolation.

### 8.2 Long protocol — the 40 % VAS force

Run at pre-S, post-S and post-I. **Ascend from an informed prior → 3 adjacent filaments × 3
repetitions in pseudorandom order → estimate with a fixed slope.**

1. **Search.** Start at the filament given by the prior: a configured default at pre-S of
   session 1, otherwise the previous time point's estimate shifted by a configured expected
   offset (about −2.7 ladder steps from pre-S to post-S). Apply, take the rating, step **up**
   below 40 and **down** at or above 40, until the crossing is bracketed. The search must be
   able to move in both directions. Log the start filament.
2. **Measure.** Three repetitions at each of three filaments — the crossing filament and the
   two immediately below it — in pseudorandom order. Search trials are recorded but do not
   enter the estimate.
3. **Estimate.** Fit `VAS = m · log₁₀(F) + c` to the measurement trials with **m held fixed**
   at the configured slope prior, solve for VAS = 40. Report F₄₀ in mN as the outcome; use the
   nearest available filament for the short protocol. Store every force/rating pair.

Fixing the slope is the central design decision, not an optimisation: three adjacent filaments
are only about 0.9 JND apart, so a fitted slope is unstable and raises the error three- to
five-fold for the same number of painful stimuli. A slope wrong by a factor of two still beats
fitting it. See §5.3 of the comparison document.

Slope prior: start at **51.6 VAS points per log₁₀ unit**; re-estimate pooled across
participants from pilot data, never per participant.

**Site rotates on every application**, in this protocol as well as the short one. The software
names the next site; Scheuren et al. repositioned 1 cm each time to avoid sensitising primary
afferents. Log the site index.

**Trial cap:** configurable `max_applications`, default 25. On reaching it take the best
available estimate, flag it, continue.

**Out of range.** If the lowest filament is already rated at or above 40, or the highest still
below it, use the boundary filament, write an `out_of_range` flag with its direction, tell the
experimenter, continue. **Expect this to fire in a meaningful fraction of sessions** — Amir et
al. (2022) had 25.7 % of participants ineligible on range criteria with four times as many
stimulus levels as this ladder has.

**Safety rule** (Amir et al.): never apply a filament at or above one already rated
intolerable. Settled 23 Aug 2026: there is **no separate "intolerable" control**. A rating at
the top of the pain scale is the proxy, so the software raises the flag and enforces the cap,
and the participant needs no channel beyond the scale itself and the emergency stop (§10.1).

- **Trigger:** `rating_percent >= pinprick.intolerable_vas_pct`, config, the top of the scale.
- **The cap is prospective.** It is known only once the rating is in, so it constrains the
  applications *after* it, never the one that raised it.
- **Scope: per site, per time point.** The site that reached the ceiling is capped at that
  force and above, and the cap clears at the next time point, where sensitivity genuinely
  differs.
- **Escalation:** once `pinprick.intolerable_sites_for_global_cap` distinct sites are capped
  within one time point, the cap applies to **every** site, at the **lowest** force that
  reached the ceiling anywhere in that run. Site rotates over `pinprick.n_sites` sites, so a
  per-site cap alone bars one site in eight; the escalation is what stops a broadly sensitised
  participant being walked around the rotation.
- **Experimenter discretion survives as substitution.** The experimenter may apply a lower
  filament than the software asked for whenever they judge it warranted. The row records which
  filament was applied as well as which was asked for, and **the estimator fits the applied
  value, not the intended one.**

A ceiling rating is a **censored** observation — the participant had no headroom, so the true
response may be higher. It will nearly always land on a `search` trial, since measurement sits
at the crossing filament and the two below it near VAS 40, so it rarely enters the estimate.
The analysis plan should still state what happens when it does.

**Budget equally across time points.** The trial count is set by what post-S needs and applied
identically at pre-S and post-I, because F₄₀ is compared across the three and unequal counts
would give them unequal precision — which would look like a change.

### 8.3 Short protocol

Median of five VAS ratings at a fixed force. Used for SH pinprick pain at each intervention
block, and for primary hyperalgesia at pre-S, post-S and post-I.

- **Software paces the trials.** The experimenter confirms the **start of the block**, which
  triggers the participant's warning cue. Thereafter the **participant's response** advances to
  the next trial.
- **Jittered ISI**, configurable, default 13–17 s (Scheuren et al. 2023).
- **Site rotates on every application.**

Brush allodynia (primary and secondary) uses the same protocol structure with a soft goat-hair
brush instead of a filament, at pre-S, post-S and post-I.

### 8.4 Secondary hyperalgesia area mapping

Four linear paths, inward in 5 mm steps at 1 s intervals (Bilaga 1 §3.6.2).

- The software provides the **1 Hz pacing cue** and counts steps.
- The participant signals the change in sensation; the software records the step number.
- The experimenter measures the marked distances and **types the four distances in mm whenever
  convenient — this must never block the session.** The software computes the area in mm² and
  stores both.
- If distances are outstanding at session end, prompt once, then allow the session to close
  with the entry flagged missing.

---

## 9. Protocol B — touch pressure calibration

Scheme B of the comparison document. **Channel 3, the middle channel, is the reference** — it
minimises the maximum distance to any other channel along the arm and its sensitivity is
likely intermediate rather than extreme.

1. **Anchors on the reference channel.** Method of adjustment to the 10 %, 30 % and 80 % points
   on the intensity VAS, stimulus on continuously. **Two adjustments per anchor**, one from
   clearly below and one from clearly above, averaged. Log both; a large gap means the anchor
   is poorly defined for that person.
2. **Verify each anchor by rating.** Deliver the produced pressure and ask for an intensity
   rating. Adjusting to a target is magnitude *production* whereas the outcome measures are
   magnitude *estimation*, and the two differ systematically — the regression effect
   (Teghtsoonian & Teghtsoonian 1978). Record produced pressure and returned rating.
3. **Match the other four channels to the reference** by adjustment at a single level, two
   start points. Derive each channel's anchor set from the reference's by the fitted gain.
4. **Equalisation check against the reference only** — four comparisons, both orders, reference
   and test channel one after the other with a **3 s hold**. Prompt re-adjustment on mismatch.
5. **Pleasantness adjustment** with the pattern looped continuously, range **bounded to
   [P30, P80]**, two adjustments from different start points.
6. **Preference selection — in every session.** The participant is presented with the available
   activation patterns at their calibrated intensity and indicates a preference. The choice is
   recorded every time, but is **only delivered in the participant-preferred condition**.
   Running it in all three sessions is what keeps it from signalling the condition to the
   experimenter (§16), and it yields a free within-participant measure of whether preference is
   stable across visits.

   *Note for Bilaga 1:* §3.7 currently says the preference "may also be selected" in the first
   session and used in all sessions. Running it every session is compatible with that permissive
   wording but is not what it describes; the sentence is worth aligning with the implemented
   procedure.

The 10 % anchor exists so the control condition's 20 % target is **interpolated between
measured points rather than extrapolated below them**.

Stage 1 failure must be detected before stage 2 begins, since the pleasantness range is defined
by the window.

**Zero-pressure catch trials** during the comparison phase; flag if more than 20 % are reported
as felt (Berquin et al. 2010).

**End-of-calibration evenness check.** Ask once whether the movement feels even along the arm,
with a path back to rebalancing. A 3 s static match may not transfer to the moving pattern if
inflation rates differ between channels, and nothing later corrects relative imbalance.
Whether it matters is for piloting; the software must support the check so it can be answered
without a code change.

---

## 10. Participant interface

### 10.1 Response device

| Physical button | Key(s) | Function |
|---|---|---|
| Left (large) | `pageup` | Move marker left / decrease |
| Right (large) | `pagedown` | Move marker right / increase |
| Play | `escape` + `period` | **Confirm**, and the Study 1 self-start press |
| Blank screen | `f5` | **Software emergency stop** |

**`escape` must be explicitly disabled as a quit key.** The play button emits it, so a default
binding would let a participant end a session by confirming a rating. Bind only the `period`.

### 10.2 VAS

- Horizontal line, anchors per scale from Bilaga 1 §3.6.1 and §3.9.1, including the extra
  anchor at 10 % on the pain scale and at 10 % and 90 % on the touch intensity scale.
- **The marker is hidden until the first press.** It then appears at **25 % if the left button
  was pressed first, 75 % if the right was.** Log which.
- Hold-to-repeat movement; confirm with the play button.
- No numbers, no tick marks beyond the labelled anchors.
- Record: response percent, reaction time, first-press side, number of direction changes.

### 10.3 Pressure adjustment — accelerating control

Starting values, all config and pilot-tunable:

- Tap under ~150 ms → **1 kPa** (0.4 % of range).
- Hold → **5 kPa/s** after a 300 ms delay, ramping linearly to **50 kPa/s** over 1.5 s, then
  constant. Full range in about 6 s of continuous holding.

**Log every button-down and button-up with timestamps**, not just the final setting, so the
search path is recoverable. Independently enforce a **hard pressure ceiling below the hardware
maximum** and a rate limit.

### 10.4 Language

**Participant and experimenter languages are set independently** — each chooses their own.
Every participant-facing string lives in `config/text/participant_{sv,en}.yaml`, every
experimenter-facing string in `config/text/experimenter_{sv,en}.yaml`. No user-facing string in
any `.py` file. A missing key is a startup error, never a silent fallback to the other
language.

### 10.5 Cues and audio

- **A visual warning cue precedes every stimulus.**
- **Continuous white noise** to the participant's headphones at a configured level, with an
  **alert tone mixed over it** as the cue.
- Separate lab-side alerts for the experimenter — block due, rekindle approaching — which must
  not be audible to the participant over the noise.
- Timestamp every cue onset.
- Between blocks the participant screen shows a neutral standby display.

### 10.6 VAS questions and anchors

English from Bilaga 1 §3.6.1 and §3.9.1. **The Swedish is a draft to be checked against the
participant-facing ethics attachments before first use** (§20) — participant-facing wording is
bound by what the application says participants will be shown, so it is verified, not invented.
These go into `config/text/participant_{sv,en}.yaml`; nothing here belongs in code.

**Pinprick pain** — after each application.

| | English | Svenska |
|---|---|---|
| Question | How painful was the stimulus that you just felt on your hand? | Hur smärtsamt var det du just kände på handen? |
| 0 % | not at all painful | inte alls smärtsamt |
| 10 % | just painful | precis smärtsamt |
| 100 % | extremely painful | extremt smärtsamt |

**Touch intensity** — during calibration and each intervention block.

| | English | Svenska |
|---|---|---|
| Question | How intense is the current touch from the garment? | Hur intensiv är beröringen från plagget just nu? |
| 0 % | no sensation at all | ingen känsla alls |
| 10 % | just noticeable | precis märkbar |
| 90 % | just uncomfortable | precis obehaglig |
| 100 % | very intense | mycket intensiv |

**Touch pleasantness.**

| | English | Svenska |
|---|---|---|
| Question | How pleasant is the current touch from the garment? | Hur behaglig är beröringen från plagget just nu? |
| 0 % | very unpleasant | mycket obehaglig |
| 100 % | very pleasant | mycket behaglig |

**Relaxation state** — RSQ items 6 and 10 (Steghaus & Poth 2022), presented once per time
point. The Swedish is translated from the **German originals**, which are the authoritative
wording; the English in Bilaga 1 is itself the authors' translation.

| | Deutsch (original) | English | Svenska |
|---|---|---|---|
| Question | *(Appendix A of the paper)* | How accurately do the following statements describe how you feel right now? | Hur väl stämmer följande påståenden med hur du känner dig just nu? |
| Item 6 | Ich fühle mich sehr entspannt. | I'm feeling very relaxed. | Jag känner mig mycket avslappnad. |
| Item 10 (R) | Ich fühle mich erfrischt und wach. | I'm feeling refreshed and awake. | Jag känner mig pigg och vaken. |
| 0 % | | completely disagree | instämmer inte alls |
| 100 % | | completely agree | instämmer helt |

On item 10: the German is *erfrischt* (refreshed, invigorated), not *ausgeruht* (rested), so an
earlier draft's "utvilad och pigg" was the wrong sense. *Pigg och vaken* keeps the German's
pairing of an invigoration word with a wakefulness word and is the natural Swedish;
*uppfriskad och vaken* is the closer cognate but reads oddly in this context.

**VAS training — proportionality** (Price et al. 1983), given once per scale at first use.

| Scale | Svenska |
|---|---|
| Pain | Ett märke dubbelt så långt ut på linjen betyder att det gjorde dubbelt så ont. |
| Intensity | Ett märke dubbelt så långt ut på linjen betyder att beröringen kändes dubbelt så intensiv. |
| Pleasantness | Ett märke dubbelt så långt ut på linjen betyder att beröringen kändes dubbelt så behaglig. |

Settled 22 Aug 2026: **"precis smärtsamt"** for "just painful", used consistently including in
the training text; the RSQ items translated from the German as above; the pleasantness scale
made **symmetric**. Colleagues will check the Swedish during piloting.

Two deviations from Bilaga 1 that the application should be updated to match:

- **§3.9.1 gives the pleasantness anchors as "unpleasant" and "very pleasant"** — asymmetric.
  The scale is now symmetric, *mycket obehaglig* to *mycket behaglig*.
- The RSQ is a **five-point Likert instrument**; presenting its items on a VAS is an adaptation,
  which Bilaga 1 already describes as "adapted from". The published item properties and
  reliability do not transfer directly to the VAS form. Worth one sentence in the plan.


---

## 11. Experimenter interface

Displays:

- Current phase, session elapsed time, countdown to the next scheduled event.
- What to do now: which filament, which site, which path, which brush region.
- **A diagram of the primary and secondary hyperalgesic zones**, marking where the current
  stimulus should be applied. A placeholder line drawing is committed at
  `assets/hyperalgesia_zones.svg` — hand outline, filled rectangle for the primary zone, dashed
  ellipse for the secondary. Replace it when a proper figure exists; the layout is built around
  it either way. Include the monofilament delivery instructions alongside it if
  they fit without crowding — perpendicular approach, bend to about three-quarters of the
  filament's length, about 1 s, no lateral movement, slow removal.
- Confirmation that the participant's response was received.
- **Hardware status**: connection state and per-channel pressure, with a
  **disconnect/reconnect** button.

It **never displays the value of any participant rating** (Bilaga 1 §3.3 requires ratings be
made on an interface not visible to the experimenter — showing the numbers on the lab screen
would defeat that), and it **never displays the condition** (§16).

Controls: start block, pause, **discard and repeat the last trial**, abort session, timestamped
free-text note. All logged.

Discard-and-repeat exists for the case where the filament was delivered badly but the
participant still responded: the trial is marked discarded, retained in the data with its flag,
and repeated. There is deliberately **no skip-trial control** — a control that silently drops a
planned trial is a data hazard, and pause plus discard cover the real cases.

**Experimenter identity is their initials**, entered at session start and written to the
session file. If they differ from that participant's earlier sessions, warn clearly and allow
the session to continue — §3.3 asks for the same experimenter throughout, but sometimes there
is no choice, and the deviation belongs in the data rather than in a blocked session.

---

## 12. Garment control

### 12.1 The interface

`tatp/garment/base.py` defines an abstract `GarmentController`:

```
connect() / disconnect()
capabilities() -> dict                       # see below
set_pressure(channel: int, kpa: float)       # clamped to the configured ceiling
play_pattern(pattern, params: dict)
stop()                                        # immediate, all channels to zero
status() -> dict                              # per-channel pressure, connection state, faults
```

`capabilities()` reports at least `n_channels`, `pressure_range_kpa`, and
**`per_channel_pressure: bool`**. **It is declared statically by the driver class, not queried
from the device** — the hardware reports nothing of the sort, and each driver is written for
one specific rig, so the driver already knows. The bring-up checklist verifies each declaration
against the actual hardware (§18.2). It exists because the hardware arrives in stages (§12.4)
and the software must adapt rather than assume.

Three implementations:

- **`mock.py`** — no hardware. A first-class deliverable, not scaffolding: the whole system
  runs end to end against it, and every real driver is a drop-in swap behind this interface. It
  records all commands with timestamps, enforces the same clamps, and can inject faults.
- **`arduino_mosfet.py`** — the **current prototype**: MOSFET array, channels on/off only,
  overall pressure set by hand at the source. Reports `per_channel_pressure: false`.
- **`arduino_valves.py`** — the **experiment garment**: proportional valves, per-channel
  pressure. Reports `per_channel_pressure: true`.

### 12.2 Patterns

**Authoring format: the tick-grid CSV of the existing repo — one column per channel, one row
per time step, 1 for on and 0 for off.** It is easy for a human to read and write, which is the
point. **The row interval is a per-pattern parameter, not a fixed 100 ms**, so any velocity is
expressible: at 1.5 cm channel spacing, 20 cm/s means 75 ms between successive channel onsets,
so that pattern is authored with `row_interval_ms: 75`. Each pattern file carries its own
interval in a header or a sidecar YAML.

**Overlap is expressed in the CSV** by a channel remaining on across several consecutive rows
while the next channel starts. The examples in the existing repo happen to have no overlap;
that is arbitrary test data, not a design decision. Apparent motion generally needs some
overlap, and the amount is a parameter to settle in piloting (§20).

**Looping must be implemented** — patterns repeat continuously for the duration they are
active, including throughout the pleasantness adjustment (§9 step 5).

Internally the grid is expanded to timed channel events before playback so the driver is not
tied to the tick rate, but that is an implementation detail; **the CSV is the interface for
humans and the thing stored, versioned and hashed into the session file.**

**Pattern designer** (launcher entry 3, `tools/design_pattern.py`): compose and save patterns,
preview the activation timeline, and write them into a pattern folder.

**At run time the experimenter selects a pattern folder** containing all the Study 1 patterns.
The software chooses within it according to the allocation, and **never displays which pattern
or condition was selected** (§16). The condition — `participant_preferred`, `ct_targeted` or
`sham` — is written to the data files.

**Provisional mockups** to build against until the real patterns exist, assuming 1.5 cm between
adjacent channels, five channels, 6 cm span. Each is one CSV with its own row interval, so one
row equals one inter-channel step:

| Nominal velocity | `row_interval_ms` | Full five-channel sweep, no overlap |
|---|---|---|
| 1 cm/s | 1500 | 7.5 s |
| 3 cm/s (CT-optimal) | 500 | 2.5 s |
| 20 cm/s | 75 | 0.375 s |

With overlap of *k* extra rows per channel the sweep lengthens by *k* × `row_interval_ms`.
Overlap is a parameter to settle in piloting (§20).

The control condition delivers **low-intensity static sham touch**, not the absence of touch,
targeting 20 % on the intensity VAS.

### 12.3 During the session

Active through the intervention, **deactivated for the rekindle**, reactivated after. In the
participant-preferred condition the participant starts the stimulation with the confirm button.

### 12.4 Piloting against the current prototype

**Session timings can be piloted with the existing prototype before the new garment exists.**
Pattern playback is on/off timing, which the prototype does, so the schedule, the block
structure, the pinprick protocols and the duration of everything can all be exercised for real.

What the prototype cannot do is pressure control of any kind. Its control path, read from the
existing repository, is a **single bit per channel**: the Python builds a 32-bit mask with
`m |= (1 << channel_id)`, sends `setstate:0x<mask>` or `addcode:0x<mask>/<delay>`, and the
Arduino `shiftOut()`s those bits to a shift register driving the MOSFETs. There is no
`analogWrite` and no PWM anywhere in the sketch or the Python. Overall pressure is set by hand
at the regulator and the software never sees it. So `per_channel_pressure: false` for this rig
is a fact about the hardware, not a guess.

**A related defect worth not inheriting.** `Controller.Stimulus.from_csv_matrix_vertical`
parses each cell with `int(x)` and then tests `val == 1` for onset and `val == 0` for offset.
A non-integer cell such as `0.5` raises `ValueError`; an integer of 2 or more parses fine and
then matches **neither** test, so it is silently skipped — the channel gets no onset, or worse,
if it was already on, **no offset, and stays pressurised**. Any pattern loader written here
must validate cell values explicitly and refuse anything that is not 0 or 1, and every channel
that turns on must be proven to turn off. Note also that channel IDs are used directly as bit
positions, so an ID is a hardware bit index rather than an ordinal.

Because per-channel pressure is unavailable, Protocol B's anchor-and-match procedure
(§9 steps 1–4) cannot be run properly against the prototype. When `capabilities()` reports
`per_channel_pressure: false` the software must:

- run Protocol B in a **timing-only mode**: the adjustment and comparison steps happen with
  their real interaction and their real durations, so the time budget is measurable, but the
  resulting pressures are recorded as **not valid for analysis**;
- write a `reduced_capability_device` flag and the driver name into the session file;
- show a persistent, unmissable banner on the experimenter screen saying this session is not
  collecting valid touch-calibration data.

This is a warning, not a refusal — piloting is exactly what it is for. But a session run this
way must be impossible to mistake for a real one afterwards.

---

## 13. Safety

- **The hardware emergency stop is the real safety path.** The participant's physical button
  and the rapid depressurisation mechanism act without the software, which must never be in the
  path that makes them work.
- **Software emergency stop** on `f5`: immediately commands all channels to zero, logs the
  press, pauses, and offers resume. Bilaga 1 §3.10 says participants are told pressing it will
  not disturb the experiment, so resumption must be genuinely clean.
- Hard pressure ceiling and rate limit in software, below the hardware maximum, independent of
  participant adjustment.
- The session can be stopped at any point by either party with all data intact.
- Every stop, pause and resume is logged with its origin.

---

## 14. Data output

### 14.1 Where

Default `data/` inside the repository, **gitignored**. Configurable in `hardware.yaml`.
Transferred manually to the LiU secure server afterwards.

If the configured data folder resolves inside a cloud-synced tree — OneDrive, Dropbox, iCloud —
**warn clearly at startup and record the fact in the session file, but do not refuse to run.**

No direct personal identifiers in any file. Participant code only.

### 14.2 Files

**One file per observational unit.** A single long file would force unrelated things into one
column set; separate files keep each table tidy (Wickham 2014). Files continue across phases
wherever the structure matches — the phase is a column, not a reason for a new file.

Named `TATP1_{YYYY-MM-DD_HH-MM-SS}_P{code}_S{session}_{table}.csv`:

| Table | One row per | Notes |
|---|---|---|
| `session` | key/value pair | Provenance; see below |
| `log` | event | Phase transitions, block boundaries, cue onsets, button events, experimenter actions, warnings, notes, errors |
| `pinprick` | monofilament application | All phases, both protocols; `protocol` column distinguishes long from short. Force, site, rating, RT, flags |
| `calibration_pinprick` | completed long protocol | Derived F₄₀, chosen filament, applications used, slope used, `out_of_range` |
| `brush` | brush application | Allodynia, primary and secondary regions |
| `mapping` | mapping path | Phase, path id, steps counted, measured distance in mm |
| `sh_area` | phase | Computed area in mm² and the distances it came from |
| `touch_ratings` | touch VAS rating | Intensity, pleasantness, relaxation, alertness; TC baseline and each intervention block |
| `touchcal_adjust` | adjustment | Channel, anchor, start direction, produced pressure, verification rating |
| `touchcal_compare` | comparison | Channel pair, order, judgement, any re-adjustment |
| `garment` | command issued | Timestamp, channel, pressure, pattern event |

`_session.csv` holds: participant code, session number, condition, limb, experimenter initials,
participant and experimenter languages, RNG seed, schedule and allocation file hashes, pattern
folder and hashes, software version, git SHA, Python and Qt versions, filament calibration date,
slope prior, room temperature and humidity if entered, cloud-sync warning if raised, start and
end times, abort reason if any.

Write `docs/DATA_SCHEMA.md` with the exact column list, type and unit for every table
**before** writing the writer. The validator asserts against it.

### 14.3 Durability

Every row is appended and flushed **as it is produced**, following `DataFileCollection`'s
open-append-close pattern. A crash at any moment loses at most the trial in progress. Filenames
are unique by timestamp; the software never overwrites an existing data file.

---

## 15. Crash recovery

On restart the software detects an open session for that participant and session number, shows
what was completed and how long ago sensitisation began, and offers to **resume from the last
completed block keeping the original session t=0.** Calibrated forces, touch calibration
parameters and the RNG state are reloaded, not redone. Resumption is logged and flagged in the
session file. The clock is reconstructed from the recorded sensitisation start time, not from
process start.

---

## 16. Blinding and participant framing

Binding constraints from Bilaga 1 §3.3 and the participant-facing documents:

- **Nothing the participant sees may state or imply that touch is expected to relieve pain.**
  Frame everything as investigating pleasant and unpleasant bodily sensations, and how touch and
  pain are experienced together.
- **Do not name the research environment** (Touch away the pain / TATP) anywhere
  participant-facing. The name states the hypothesis.
- **Give no distinguishing detail about any one condition.** The participant may be told there
  are three different kinds of touch, one per visit. Nothing more.
- **No condition labels on the participant screen**, and no internal variable names rendered to
  it.
- **No condition labels on the experimenter screen either.** The condition and the selected
  pattern are recorded in the data and never displayed.
- The experimenter screen never shows rating values (§11).

**Two measures make the experimenter blind in practice.** First, **the preference selection
runs at the start of every session**, not only in the sessions where it is used (§9 step 6), so
its presence is not a tell. Second, the experimenter is not told what the conditions are, so
differences they notice — a static stimulus, a fast or slow sweep — carry no meaning for them.
S handles the framing verbally so that an observed difference does not read as a fault.

**Known and managed limitation.** This is not a guaranteed blind: an experimenter who runs many
sessions may infer the structure. It is recorded as a limitation rather than claimed as a
property. The software's obligation is narrower and absolute — it must never be the thing that
reveals the condition.

Tests assert that no participant-facing text file contains the forbidden terms, and the
screenshot manifest includes a check that no condition label appears on either screen.

---

## 17. Verification — the definition of done

### 17.1 The gate

`make check` runs unit tests, then the end-to-end validator, then the screenshot comparison,
and exits non-zero listing every failure. **This is the gate. The work is not done until it
passes with no hardware attached.** It must run headless under `QT_QPA_PLATFORM=offscreen`.

### 17.2 Unit tests

pytest, for everything with a definite right answer:

- Calibration search: crossing detection, direction changes, bracket selection, trial cap, both
  out-of-range paths.
- The fixed-slope estimator: known inputs → known F₄₀; behaviour when ratings are identical.
- Gain fitting between channels.
- Schedule generation, override application, each validation warning.
- Allocation reading; limb derivation from session number.
- Counterbalancing balanced over many seeds; each participant's allocation stable.
- Seed reproducibility: same seed → identical trial order.
- Resume: a truncated data file reconstructs the correct state.
- Data writers: schema conformance for every table; append-on-crash behaviour.
- Pressure clamping and the accelerating adjustment curve.
- Pattern loading and event timing, including 75 ms onset intervals.
- The no-literals grep and the forbidden-terms check.

### 17.3 End-to-end validator

`tools/validate_session.py` runs a complete session headless — mock garment, virtual
participant, virtual experimenter, accelerated clock — then opens the data files and asserts:

- Every expected table exists with the columns `DATA_SCHEMA.md` specifies, and no missing values
  in required fields.
- Row counts match the schedule; every scheduled block appears, in order.
- Condition and limb match the allocation file for that participant and session.
- Timestamps monotonic; intervals within tolerance; planned versus actual offsets recorded.
- Same seed reproduces an identical trial order.
- The calibrated force is one of the filaments in `filaments.yaml`.
- `out_of_range` set when and only when it should be.
- All provenance fields populated.
- No text violating §16 appears anywhere in the participant-facing configuration.

### 17.4 Screenshots, manifest and per-screen approval

`tatp/screenshots.py` walks every screen state and writes a numbered PNG with `QWidget.grab()`:
every instruction screen in both languages for both roles, the VAS at several marker positions
and both first-press sides, the warning cue, the standby screen, the experimenter screen for
each block type including the zone diagram, the adjustment screen, the hardware status panel,
and the abort and error dialogs.

A **manifest** (`screenshots/manifest.yaml`) lists every expected state with a description of
what the image should show. A manifest entry with no image is a failure; an image with no entry
is a failure.

**Pixel-diff regression is per screen.** Each entry either has an approved reference in
`screenshots/reference/` or does not. A screen with a reference is compared and any difference
beyond a configured tolerance fails; a screen without one is not compared. Approving a screen
arms it; deliberately changing one means reviewing the diff and re-approving, with
`--approve-all` for a wording pass. This protects finished screens from collateral damage during
the build without fighting intentional edits during piloting.

A **freeze** command requires every entry to have an approved reference and every diff clean,
and records the git SHA at freeze. That SHA goes into every subsequent data file, so any session
traces to the exact interface the participant saw.

### 17.5 Virtual participants and experimenters

`sim/responders.py` — **normal**: the observer model from `calibration_sim.py`,
rating = 40 + m·(log₁₀F − log₁₀F₄₀) + noise. **Adversarial**, each asserting a specific error
path fires: rates everything 0; rates everything 100; rates randomly; F₄₀ below the bottom
filament; F₄₀ above the top; confirms instantly without moving the marker; presses the emergency
stop mid-block; stops responding; holds the pressure adjustment to maximum.

`sim/experimenters.py` — **normal**, plus adversarial: enters a participant code and session
number that already have a completed session; enters session 3 before session 2; enters
different initials from that participant's earlier sessions; enters a participant code absent
from the allocation file; enters implausible mapping distances (zero, negative, larger than the
arm); disconnects the garment mid-block; closes the window mid-block; starts a second instance
while one is running; leaves mapping distances unentered at session end. Each asserts the
software refuses, warns or recovers as specified, and that no data is lost.

### 17.6 Adversarial review

Before declaring the build done, use a subagent in a fresh context to review the diff against
this spec: is every requirement implemented, are the stated edge cases tested, has anything
outside scope changed. Report gaps affecting correctness or a stated requirement — not style
preferences, not speculative hardening.

---

## 18. Build sequence

**Vertical slice first.** One thin complete path through every layer before widening any of
them. Mock hardware throughout; real garment work happens at the bring-up session (§18.2).

**Milestone 1 — the slice.** One participant, one calibration of three applications, one
pinprick trial, one touch rating, mock garment, real config, real data files with full
provenance, end to end producing valid files. Trivial as an experiment, complete as a system.

**Milestone 2 — the checks.** `make check` exists and passes: unit tests for what exists, the
validator, screenshot mode and manifest. Every later change is then defended by a working gate.

**Milestone 3 — Protocol A in full.** Long protocol with real search, measurement and
fixed-slope estimate; short protocol with jittered ISI and site rotation; brush; SH area
mapping. Unit-tested against `calibration_sim.py`.

**Milestone 4 — Protocol B in full.** Adjustment with accelerating control, anchors, gain
matching, equalisation, pleasantness.

**Milestone 5 — the session.** Full schedule, all twelve intervention blocks, rekindle handling,
resume, experimenter interface with the zone diagram and hardware panel, alerts, audio.

**Milestone 6 — pilotable.** SOP and README written, screenshots frozen, adversarial review
done.

### 18.1 Timeline

A pilotable mock-hardware version is wanted **within weeks**, to settle the §7 timings.
Milestones 1–3 and 5 are on that path; Milestone 4 can follow if the garment is not yet
available for the touch-calibration timings.

### 18.2 Hardware bring-up

A separate session with the experimenter, against the real garment. Produce
`HARDWARE_BRINGUP.md`: serial connection; per-channel identification and mapping to physical
position, including which bit index each channel occupies; **verification that the driver's
`capabilities()` declaration matches the hardware** (§12.1); pressure calibration against a
gauge; **inflation-rate measurement per channel**; a check that every channel commanded on is
observed to turn off; emergency-stop verification, hardware and software; and a full
mock-versus-real comparison run. Nothing on this list is attempted before that session.

---

## 19. Running Claude Code on this project

Already in place: `CLAUDE.md`, `.gitignore`, and — staged at `setup/claude/` for moving into
`.claude/` — `settings.json` and `hooks/check_bash.py`.

The permission rules allow file operations inside the repository, the test and tool commands,
read-only git plus add and commit, and documentation domains. They deny `git push`, `rm`, `mv`,
`pip install`, `sudo`, reads and writes under `~/Library/CloudStorage`, reads and writes under
`data/`, and all MCP tools. `disabledMcpjsonServers` is set to `["*"]`; this project needs no
MCP servers, and removing them removes a class of uncertainty rather than managing it.

The `PreToolUse` hook on `Bash` exists because permission patterns match the command string and
a compound command can satisfy a rule written for its first clause. It reads the tool call as
JSON on **stdin**, and exits 2 — which blocks the call and returns the message to the model — if
the command contains `&&`, `||`, `;`, `|`, `$(`, a backtick or a newline, or references a path
outside the repository. CLAUDE.md carries the matching instruction so compliance is the default
rather than a fight with the hook; the instruction is advisory, the hook is what makes it hold.

---

## 20. Open items — values needed before first use

Configuration placeholders, clearly marked. The software warns at startup for each unresolved
one.

1. **Measured filament forces** and weighing date — via the instruments module (§8.1).
2. **Garment pressure resolution** and the proportional-valve controller's serial protocol.
3. **Inflation rate per channel** — needed to know whether the 3 s static match transfers to the
   moving pattern (§9), and to set pattern activation durations.
4. **The session schedule grid** — block spacing, and whether the twelve rating blocks plus the
   rekindle define it. From piloting (§7).
5. **Real intervention patterns** — the mockups in §12.2 are provisional. Also the per-channel
   activation duration and overlap, and the actual inter-channel spacing if not 1.5 cm.
6. **Slope prior** — 51.6 VAS points per log₁₀ unit is a simulated starting value; replace with
   a pooled estimate from pilot data (§8.2).
7. **Expected pre-S → post-S offset** for the informed prior — about −2.7 ladder steps from
   Scheuren et al.; confirm against pilot data.
8. **Duration of one touch adjustment** — decides whether the Protocol B time budget holds.
9. **Screen resolutions and indices** for the lab PC.
10. **The counterbalancing file** for 41 participants, generated once by
    `tools/make_allocation.py` and committed.
11. **A proper hyperalgesic-zone figure** to replace the placeholder now at
    `assets/hyperalgesia_zones.svg` (§11). Not blocking.
12. **Verification of the drafted Swedish VAS wordings** in §10.6 against the participant-facing
    ethics attachments, plus the three points listed there.
13. **Overlap between consecutive channel activations** in the apparent-motion patterns (§12.2).
14. **The serial protocol for the proportional-valve controller.** The prototype's protocol
    carries a *bitmask* — one bit per channel — which cannot express a per-channel pressure. The
    new controller needs a command that carries a value per channel, so this is a protocol
    change to agree with whoever builds it, not just a driver change. Settle it before
    `arduino_valves.py` is written.

---

## 21. Definition of done

`make check` passes headless with no hardware: unit tests green, the validator producing valid
data files from a complete simulated session with both normal and adversarial participants and
experimenters, every screenshot matching its manifest entry and approved reference. The
adversarial review reports no gap affecting correctness or a stated requirement. README, SOP and
`HARDWARE_BRINGUP.md` written.

Anything in §20 still unresolved is listed explicitly in the final report, never quietly
defaulted.
